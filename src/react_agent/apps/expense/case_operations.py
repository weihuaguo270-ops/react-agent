"""H2 operations used by ExpenseCaseStore. All identity/config inputs are trusted.

Case row locks serialize operations and scans. No HTTP, Claim writes, case
resolution or outbound delivery. Additive tables work with existing H1 schemas.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import timedelta

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Table, Text, select

from .handoff import HandoffError, QueueId, Role, SLAPolicy, TERMINAL_STATUSES, validate_transition
from .sla import deadlines, utc
from .notifications import notification_kind
from .store import ExpenseStoreError, _fingerprint, _json


class CaseOperations:
    def _init_operations(self, metadata):
        if "expense_case_work" in metadata.tables:
            self._work = metadata.tables["expense_case_work"]
            self._actions = metadata.tables["expense_case_actions"]
            return
        self._work = Table(
            "expense_case_work", metadata,
            Column("case_id", String(128), ForeignKey(self._cases.c.case_id), primary_key=True),
            Column("case_version", Integer, nullable=False),
            Column("assignee_id", String(200)),
            Column("lock_expires_at", DateTime(timezone=True)),
            Column("responded_at", DateTime(timezone=True)),
            Column("response_due_at", DateTime(timezone=True)),
            Column("resolution_due_at", DateTime(timezone=True)),
            Column("response_breached", Boolean, nullable=False),
            Column("resolution_breached", Boolean, nullable=False),
            Column("escalation_level", Integer, nullable=False),
            Column("queue_json", Text, nullable=False),
            Column("sla_json", Text, nullable=False),
            Column("routing_rule_version", String(200), nullable=False),
            Column("routing_error", String(80)),
            CheckConstraint("case_version > 0 AND escalation_level >= 0"),
            CheckConstraint("(assignee_id IS NULL AND lock_expires_at IS NULL) OR (assignee_id IS NOT NULL AND lock_expires_at IS NOT NULL)"),
        )
        self._actions = Table(
            "expense_case_actions", metadata,
            Column("case_id", String(128), ForeignKey(self._cases.c.case_id), primary_key=True),
            Column("idempotency_key", String(180), primary_key=True),
            Column("actor_id", String(200), nullable=False),
            Column("actor_role", String(32), nullable=False),
            Column("auth_queue_json", Text, nullable=False),
            Column("fingerprint", String(200), nullable=False),
            Column("result_json", Text, nullable=False),
        )

    def _work_state(self, connection, row, *, ensure=False):
        stored = connection.execute(select(self._work).where(self._work.c.case_id == row["case_id"])).mappings().first()
        if stored is not None:
            return dict(stored)
        snapshot = json.loads(row["snapshot_json"])
        policy = snapshot.get("sla")
        response, resolution = deadlines(row["created_at"], SLAPolicy(**policy) if policy else None)
        state = dict(case_id=row["case_id"], case_version=1, assignee_id=None, lock_expires_at=None,
            responded_at=None, response_due_at=response, resolution_due_at=resolution,
            response_breached=False, resolution_breached=False, escalation_level=0,
            queue_json=_json(snapshot.get("queue_definition")), sla_json=_json(policy),
            routing_rule_version=row["routing_rule_version"], routing_error=snapshot.get("error_code"))
        if ensure:
            # Caller owns the case lock (or has just inserted the case).
            connection.execute(self._work.insert().values(**state))
        return state

    @staticmethod
    def _can_process(actor, queue):
        return bool(queue and queue["queue_id"] in actor.queue_ids and actor.role in queue["allowed_roles"])

    def _process_access(self, actor, queue, row):
        if self._can_process(actor, queue):
            return
        if row["status"] == "unrouted" and actor.role == Role.EXPENSE_OPERATOR and QueueId.EXPENSE_OPERATIONS in actor.queue_ids:
            return
        raise ExpenseStoreError("queue_not_allowed", "queue processing membership is required", status_code=403)

    def _operation_row(self, connection, case_id):
        # Same Claim -> case lock order as H1 creation, never the reverse.
        row = connection.execute(select(self._cases).where(self._cases.c.case_id == case_id)).mappings().first()
        if row is None:
            raise self._not_found()
        claim = self._claims_store._get_claim_row(connection, row["claim_id"], lock=True)
        row = connection.execute(self._locked(select(self._cases).where(self._cases.c.case_id == case_id))).mappings().one()
        return dict(row), claim

    @staticmethod
    def _reason(reason):
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 500:
            raise ExpenseStoreError("invalid_handoff", "a non-empty reason of at most 500 characters is required", status_code=400)
        return reason.strip()

    def _change(self, connection, row, state, *, actor, request_id, event_type, reason,
                status=None, queue=None, routing_version=None, state_changes=None, notify=False, event_key=None,
                metadata=None):
        before_status, before_queue, before_assignee = row["status"], row["queue_id"], state["assignee_id"]
        before_lock, before_routing = state["lock_expires_at"], state["routing_rule_version"]
        status = status or before_status
        if status != before_status:
            try:
                validate_transition(before_status, status)
            except HandoffError as exc:
                raise ExpenseStoreError(str(exc.code), str(exc)) from exc
        row["status"] = status
        if queue is not None:
            row["queue_id"] = queue["queue_id"]
            state["queue_json"] = _json(queue)
        if status == "unrouted":
            row["queue_id"] = None
            state["queue_json"] = "null"
        if routing_version is not None:
            state["routing_rule_version"] = routing_version
        state.update(state_changes or {})
        state["case_version"] += 1
        connection.execute(self._cases.update().where(self._cases.c.case_id == row["case_id"]).values(
            status=row["status"], queue_id=row["queue_id"], priority=row["priority"],
            routing_rule_version=state["routing_rule_version"]))
        connection.execute(self._work.update().where(self._work.c.case_id == row["case_id"]).values(**state))
        event_id = self._append(connection, row, event_key=event_key or "h2:" + uuid.uuid4().hex,
            event_type=event_type, actor=actor, request_id=request_id, from_status=before_status,
            metadata={"reason": reason, "from_queue": before_queue, "to_queue": row["queue_id"],
                "previous_assignee_id": before_assignee, "assignee_id": state["assignee_id"],
                "previous_lock_expires_at": utc(before_lock).isoformat() if before_lock else None,
                "lock_expires_at": utc(state["lock_expires_at"]).isoformat() if state["lock_expires_at"] else None,
                "previous_routing_rule_version": before_routing,
                "previous_case_version": state["case_version"] - 1, "case_version": state["case_version"],
                "routing_rule_version": state["routing_rule_version"], "error_code": state["routing_error"],
                "escalation_level": state["escalation_level"], **(metadata or {})})
        if notify:
            connection.execute(self._outbox.insert().values(outbox_id="out_" + uuid.uuid4().hex,
                case_id=row["case_id"], event_id=event_id, notification_type=notification_kind(event_type),
                target_queue=row["queue_id"] or QueueId.EXPENSE_OPERATIONS, status="pending",
                payload_json=_json({"case_id": row["case_id"], "event_id": event_id}), created_at=self._now()))

    def _fail_route(self, connection, row, state, *, actor, request_id, reason, error, routing):
        changes = dict(assignee_id=None, lock_expires_at=None, routing_error=error)
        if row["status"] in {"assigned", "in_progress"}:
            self._change(connection, row, state, actor=actor, request_id=request_id,
                event_type="case_escalated", reason=reason, status="escalated",
                state_changes={**changes, "escalation_level": state["escalation_level"] + 1})
        if row["status"] != "unrouted" or state["routing_error"] != error:
            row["priority"] = "urgent" if row["priority"] == "urgent" else "high"
            self._change(connection, row, state, actor=actor, request_id=request_id,
                event_type="case_unrouted", reason=reason, status="unrouted", state_changes=changes,
                routing_version=routing.routing_rule_version, notify=True)

    def _expire_lock(self, connection, row, state, *, actor, request_id, now):
        if state["lock_expires_at"] is not None and utc(state["lock_expires_at"]) <= now:
            self._change(connection, row, state, actor=actor, request_id=request_id,
                event_type="claim_lock_expired", reason="claim lock expired", status="queued",
                state_changes={"assignee_id": None, "lock_expires_at": None})

    def _route_to(self, connection, row, state, *, actor, request_id, routing, target, reason, escalating):
        queue = next((q for q in routing.queues if q.queue_id == target), None)
        if queue is None or not queue.available:
            self._fail_route(connection, row, state, actor=actor, request_id=request_id, reason=reason,
                error="unrouted_case" if queue is None else "queue_unavailable", routing=routing)
            return
        if escalating and queue.queue_id == row["queue_id"]:
            self._fail_route(connection, row, state, actor=actor, request_id=request_id, reason=reason,
                error="invalid_routing_config", routing=routing)
            return
        if not escalating and row["status"] == "queued" and queue.queue_id == row["queue_id"]:
            raise ExpenseStoreError("invalid_case_transition", "case is already queued here")
        changes = dict(assignee_id=None, lock_expires_at=None, routing_error=None)
        if json.loads(state["sla_json"]) is None:
            # Previously unrouted H1 case: first successful routing freezes a policy,
            # using ORIGINAL creation time, never extending the age of the case.
            response, resolution = deadlines(row["created_at"], queue.sla)
            changes.update(sla_json=_json(asdict(queue.sla)), response_due_at=response, resolution_due_at=resolution)
        if escalating:
            changes["escalation_level"] = state["escalation_level"] + 1
            row["priority"] = "urgent" if row["priority"] == "urgent" else "high"
        self._change(connection, row, state, actor=actor, request_id=request_id,
            event_type="case_escalated" if escalating else "case_transferred", reason=reason,
            status="escalated" if escalating else "queued", queue=asdict(queue),
            routing_version=routing.routing_rule_version, state_changes=changes, notify=True)

    def _act(self, case_id, *, operation, actor, expected_case_version, request_id, idempotency_key,
             routing=None, reason=None, target_queue_id=None):
        from .case_store import _token
        _token(request_id, "request_id")
        _token(idempotency_key, "idempotency_key", limit=180)
        if type(expected_case_version) is not int or expected_case_version < 1:
            raise ExpenseStoreError("case_version_conflict", "positive expected_case_version required")
        if operation in {"transfer", "escalate", "release"}:
            reason = self._reason(reason)
        if target_queue_id is not None:
            try:
                target_queue_id = QueueId(target_queue_id)
            except (ValueError, TypeError) as exc:
                raise ExpenseStoreError("queue_not_allowed", "unknown target queue", status_code=403) from exc
        fingerprint = _fingerprint(dict(operation=operation, actor_id=actor.actor_id, role=actor.role,
            expected_case_version=expected_case_version, reason=reason, target_queue_id=target_queue_id))
        with self._transaction() as connection:
            row, claim = self._operation_row(connection, case_id)
            previous = connection.execute(select(self._actions).where(self._actions.c.case_id == case_id,
                self._actions.c.idempotency_key == idempotency_key)).mappings().first()
            if previous is not None:
                if (previous["actor_id"], previous["actor_role"]) != (actor.actor_id, actor.role):
                    raise self._not_found()
                # A successful transfer removes the caller from the new queue. Replay
                # still requires the original trusted processing membership.
                auth = json.loads(previous["auth_queue_json"])
                self._process_access(actor, auth, {"status": "queued" if auth else "unrouted"})
                if previous["fingerprint"] != fingerprint:
                    raise ExpenseStoreError("idempotency_conflict", "case action key payload differs")
                return {**json.loads(previous["result_json"]), "idempotent_replay": True}
            self._authorize(connection, row, actor)
            state = self._work_state(connection, row, ensure=True)
            auth_queue = json.loads(state["queue_json"])
            self._process_access(actor, auth_queue, row)
            now = self._now()
            live_lock = state["assignee_id"] and utc(state["lock_expires_at"]) > now
            if operation == "claim" and live_lock and state["assignee_id"] != actor.actor_id:
                raise ExpenseStoreError("case_already_claimed", "case is claimed by another processor")
            if state["case_version"] != expected_case_version:
                raise ExpenseStoreError("case_version_conflict", "case version changed")
            if claim is None or claim["current_version"] != row["claim_version"]:
                raise ExpenseStoreError("claim_version_mismatch", "Claim version changed")
            if row["status"] in TERMINAL_STATUSES:
                raise ExpenseStoreError("invalid_case_transition", "terminal case cannot be changed")
            if row["status"] == "needs_applicant":
                raise ExpenseStoreError("invalid_case_transition", "waiting case requires explicit applicant resume")
            if live_lock and state["assignee_id"] != actor.actor_id:
                raise ExpenseStoreError("case_already_claimed", "only the current processor may change this lock")
            if operation == "release" and state["assignee_id"] != actor.actor_id:
                raise ExpenseStoreError("case_not_claimable", "no owned processing lock to release")
            self._expire_lock(connection, row, state, actor=actor, request_id=request_id, now=now)
            if operation == "claim":
                if row["status"] != "queued":
                    raise ExpenseStoreError("case_not_claimable", "only queued cases can be claimed")
                live_queue = next((q for q in routing.queues if q.queue_id == row["queue_id"]), None)
                if live_queue is None or not live_queue.available:
                    self._fail_route(connection, row, state, actor=actor, request_id=request_id,
                        reason="claim queue unavailable", error="queue_unavailable" if live_queue else "unrouted_case", routing=routing)
                else:
                    if not self._can_process(actor, asdict(live_queue)):
                        raise ExpenseStoreError("queue_not_allowed", "current queue policy denies processor", status_code=403)
                    self._change(connection, row, state, actor=actor, request_id=request_id,
                        event_type="case_claimed", reason="queue member claimed case", status="assigned",
                        queue=asdict(live_queue), routing_version=routing.routing_rule_version,
                        state_changes={"assignee_id": actor.actor_id, "lock_expires_at": now + timedelta(seconds=self._claim_lock_seconds),
                            "responded_at": state["responded_at"] or now}, notify=True)
            elif operation == "release":
                if state["assignee_id"] != actor.actor_id:
                    # An expired lease was just released above; do not produce another event.
                    if not live_lock and row["status"] == "queued" and expected_case_version < state["case_version"]:
                        pass
                    else:
                        raise ExpenseStoreError("case_not_claimable", "no owned processing lock to release")
                else:
                    self._change(connection, row, state, actor=actor, request_id=request_id,
                        event_type="case_released", reason=reason, status="queued",
                        state_changes={"assignee_id": None, "lock_expires_at": None})
            else:
                target = target_queue_id
                if operation == "escalate":
                    target = auth_queue.get("escalate_to") if auth_queue else None
                elif target is None:
                    target = next((r.queue_id for r in routing.rules if r.reason_code == row["reason_code"]), None)
                self._route_to(connection, row, state, actor=actor, request_id=request_id, routing=routing,
                    target=target, reason=reason, escalating=operation == "escalate")
            result = self._case_result(connection, row)
            connection.execute(self._actions.insert().values(case_id=case_id, idempotency_key=idempotency_key,
                actor_id=actor.actor_id, actor_role=actor.role, auth_queue_json=_json(auth_queue),
                fingerprint=fingerprint, result_json=_json(result)))
            return result

    def claim_case(self, case_id, *, actor, expected_case_version, request_id, idempotency_key, routing):
        """Self-claim only; callers cannot supply an assignee_id."""
        return self._act(case_id, operation="claim", actor=actor, expected_case_version=expected_case_version,
            request_id=request_id, idempotency_key=idempotency_key, routing=routing)

    def release_case(self, case_id, *, actor, expected_case_version, request_id, idempotency_key, reason):
        return self._act(case_id, operation="release", actor=actor, expected_case_version=expected_case_version,
            request_id=request_id, idempotency_key=idempotency_key, reason=reason)

    def transfer_case(self, case_id, *, actor, expected_case_version, request_id, idempotency_key, routing, reason, target_queue_id=None):
        return self._act(case_id, operation="transfer", actor=actor, expected_case_version=expected_case_version,
            request_id=request_id, idempotency_key=idempotency_key, routing=routing, reason=reason, target_queue_id=target_queue_id)

    def escalate_case(self, case_id, *, actor, expected_case_version, request_id, idempotency_key, routing, reason):
        return self._act(case_id, operation="escalate", actor=actor, expected_case_version=expected_case_version,
            request_id=request_id, idempotency_key=idempotency_key, routing=routing, reason=reason)

    def scan_sla(self, *, actor, routing, request_id, limit=100, after_case_id=None, warning_before_seconds=0):
        """One bounded page, per-case transactions; trusted finance-admin maintenance only.

        Breach markers and events commit together. Repeating/concurrent scans never
        repeat a deadline escalation; expired processing leases only unlock cases.
        """
        from .case_store import _token
        _token(request_id, "request_id")
        if actor.role != Role.FINANCE_ADMIN:
            raise ExpenseStoreError("queue_not_allowed", "trusted maintenance role required", status_code=403)
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ExpenseStoreError("invalid_handoff", "scan limit must be between 1 and 1000", status_code=400)
        if type(warning_before_seconds) is not int or not 0 <= warning_before_seconds <= 86400:
            raise ExpenseStoreError("invalid_handoff", "warning window must be 0..86400 seconds", status_code=400)
        with self._engine.connect() as connection:
            stmt = select(self._cases.c.case_id).where(self._cases.c.status.not_in(TERMINAL_STATUSES))
            if after_case_id:
                stmt = stmt.where(self._cases.c.case_id > after_case_id)
            ids = connection.execute(stmt.order_by(self._cases.c.case_id).limit(limit + 1)).scalars().all()
        changed, conflicts = [], []
        for case_id in ids[:limit]:
            with self._transaction() as connection:
                row, claim = self._operation_row(connection, case_id)
                if row["status"] in TERMINAL_STATUSES:
                    continue
                if claim is None or claim["current_version"] != row["claim_version"]:
                    conflicts.append({"case_id": case_id, "error_code": "claim_version_mismatch"})
                    continue
                # H3 owns the wait-for-applicant/resume lifecycle. Never invent a
                # needs_applicant -> escalated edge or resume business work here.
                if row["status"] == "needs_applicant":
                    conflicts.append({"case_id": case_id, "error_code": "invalid_case_transition"})
                    continue
                state = self._work_state(connection, row, ensure=True)
                version = state["case_version"]
                now = self._now()
                self._expire_lock(connection, row, state, actor=actor, request_id=request_id, now=now)
                live = next((q for q in routing.queues if q.queue_id == row["queue_id"]), None)
                if row["queue_id"] and (live is None or not live.available):
                    self._fail_route(connection, row, state, actor=actor, request_id=request_id,
                        reason="scan found queue unavailable", error="queue_unavailable" if live else "unrouted_case", routing=routing)
                resolution = (state["resolution_due_at"] is not None and utc(state["resolution_due_at"]) <= now
                              and not state["resolution_breached"])
                response = (state["response_due_at"] is not None and utc(state["response_due_at"]) <= now
                            and (state["responded_at"] is None or
                                 utc(state["responded_at"]) > utc(state["response_due_at"]))
                            and not state["response_breached"])
                if resolution or response:
                    if resolution:
                        queue = json.loads(state["queue_json"])
                        self._route_to(connection, row, state, actor=actor, request_id=request_id,
                            routing=routing, target=queue.get("escalate_to") if queue else None,
                            reason="resolution SLA breached", escalating=True)
                    for kind, breached in (("response", response), ("resolution", resolution)):
                        if breached:
                            self._change(connection, row, state, actor=actor, request_id=request_id,
                                event_type=f"sla_{kind}_breached", reason=f"{kind} SLA breached",
                                state_changes={f"{kind}_breached": True}, event_key=f"sla:{kind}",
                                notify=True)
                if warning_before_seconds:
                    for kind in ("response", "resolution"):
                        due = state[f"{kind}_due_at"]
                        if (due is None or state[f"{kind}_breached"] or
                                (kind == "response" and state["responded_at"] is not None) or
                                not now < utc(due) <= now + timedelta(seconds=warning_before_seconds)):
                            continue
                        key = f"sla:warning:{kind}"
                        existing = connection.execute(select(self._events.c.event_id).where(
                            self._events.c.case_id == case_id, self._events.c.event_key == key)).first()
                        if not existing:
                            self._change(connection, row, state, actor=actor, request_id=request_id,
                                event_type=f"sla_{kind}_warning", reason=f"{kind} SLA approaching",
                                event_key=key, notify=True, metadata={"warning_before_seconds": warning_before_seconds})
                if version != state["case_version"]:
                    changed.append(self._case_result(connection, row))
        return {"cases": changed, "conflicts": conflicts,
                "next_cursor": ids[limit - 1] if len(ids) > limit else None}
