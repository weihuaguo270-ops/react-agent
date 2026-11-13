"""H3 storage composition. Closing work and approving a Claim are distinct.

Trusted identities only; no HTTP, workflow rerun, automatic case creation or
notification delivery. Claim -> case -> review locks share one SQL transaction.
"""
from __future__ import annotations

import json

from sqlalchemy import select

from react_agent.safety.permission_gate import permission_block_message

from .handoff import Role, TERMINAL_STATUSES
from .review import ReviewError, resolve_review
from .sla import utc
from .store import ExpenseStoreError, _fingerprint, _json


class _ReviewTransaction:
    """Give the existing gated review entrypoint the case's owned connection."""

    def __init__(self, claims, connection):
        self.claims, self.connection = claims, connection

    def resolve_review(self, approval_id, **kwargs):
        return self.claims._resolve_review_in_transaction(self.connection, approval_id, **kwargs)


class CaseResolution:
    @staticmethod
    def _case_version(state, expected):
        if type(expected) is not int or expected < 1 or expected != state["case_version"]:
            raise ExpenseStoreError("case_version_conflict", "case version changed")

    def _case_binding(self, connection, row, claim, *, claim_version, decision_hash):
        if (type(claim_version) is not int or claim_version != row["claim_version"] or
                claim is None or claim["current_version"] != claim_version):
            raise ExpenseStoreError("claim_version_mismatch", "Claim version changed")
        decisions = self._claims_store._decisions
        persisted = connection.execute(select(decisions.c.decision_hash).where(
            decisions.c.claim_id == row["claim_id"], decisions.c.version == claim_version)).scalar_one_or_none()
        if not decision_hash or decision_hash != row["decision_hash"] or decision_hash != persisted:
            raise ExpenseStoreError("approval_binding_mismatch", "case Decision binding changed")

    def _owned_case(self, row, state, actor):
        self._process_access(actor, json.loads(state["queue_json"]), row)
        if state["assignee_id"] and state["assignee_id"] != actor.actor_id:
            raise ExpenseStoreError("case_already_claimed", "only the current processor may act")
        if not state["assignee_id"] or utc(state["lock_expires_at"]) <= self._now():
            raise ExpenseStoreError("case_not_claimable", "a live owned processing lock is required")

    def _save_case_action(self, connection, row, state, *, actor, key, fingerprint, result):
        connection.execute(self._actions.insert().values(case_id=row["case_id"], idempotency_key=key,
            actor_id=actor.actor_id, actor_role=actor.role, auth_queue_json=state["queue_json"],
            fingerprint=fingerprint, result_json=_json(result)))

    def _case_lifecycle(self, case_id, *, operation, actor, expected_case_version, request_id,
                        idempotency_key, reason, claim_version=None, decision_hash=None,
                        evidence_ref=None, routing=None):
        from .case_store import _token
        _token(request_id, "request_id")
        _token(idempotency_key, "idempotency_key", limit=180)
        reason = self._reason(reason)
        if operation == "resume":
            _token(evidence_ref, "evidence_ref", limit=128)
        fingerprint = _fingerprint(dict(operation=operation, actor_id=actor.actor_id, role=actor.role,
            expected_case_version=expected_case_version, reason=reason, claim_version=claim_version,
            decision_hash=decision_hash, evidence_ref=evidence_ref))
        with self._transaction() as connection:
            row, claim = self._operation_row(connection, case_id)
            self._authorize(connection, row, actor)
            state = self._work_state(connection, row, ensure=True)
            if operation == "resume":
                if actor.role != Role.APPLICANT or claim["applicant_id"] != actor.actor_id:
                    raise self._not_found()
            else:
                self._process_access(actor, json.loads(state["queue_json"]), row)
            previous = connection.execute(select(self._actions).where(self._actions.c.case_id == case_id,
                self._actions.c.idempotency_key == idempotency_key)).mappings().first()
            if previous:
                if (previous["actor_id"], previous["actor_role"]) != (actor.actor_id, actor.role):
                    raise self._not_found()
                if previous["fingerprint"] != fingerprint:
                    raise ExpenseStoreError("idempotency_conflict", "case action key payload differs")
                return {**json.loads(previous["result_json"]), "idempotent_replay": True}
            self._case_version(state, expected_case_version)
            self._case_binding(connection, row, claim,
                claim_version=claim_version if operation == "resume" else row["claim_version"],
                decision_hash=decision_hash if operation == "resume" else row["decision_hash"])
            if operation == "resume":
                if row["status"] != "needs_applicant":
                    raise ExpenseStoreError("invalid_case_transition", "only waiting cases can resume")
                live = next((q for q in routing.queues if q.queue_id == row["queue_id"]), None)
                self._change(connection, row, state, actor=actor, request_id=request_id,
                    event_type="case_resumed", reason=reason, status="queued",
                    state_changes={"assignee_id": None, "lock_expires_at": None},
                    metadata={"evidence_ref": evidence_ref, "decision_hash": decision_hash,
                        "business_resumed": False})
                if live is None or not live.available:
                    self._fail_route(connection, row, state, actor=actor, request_id=request_id,
                        reason="resume queue unavailable", error="unrouted_case" if live is None else "queue_unavailable",
                        routing=routing)
            else:
                self._owned_case(row, state, actor)
                required = "assigned" if operation == "start" else "in_progress"
                if row["status"] != required:
                    raise ExpenseStoreError("invalid_case_transition", f"{operation} requires {required}")
                self._change(connection, row, state, actor=actor, request_id=request_id,
                    event_type="case_started" if operation == "start" else "case_needs_applicant",
                    reason=reason, status="in_progress" if operation == "start" else "needs_applicant",
                    state_changes={} if operation == "start" else {"assignee_id": None, "lock_expires_at": None},
                    notify=operation == "wait")
            result = self._case_result(connection, row)
            self._save_case_action(connection, row, state, actor=actor, key=idempotency_key,
                fingerprint=fingerprint, result=result)
            return result

    def start_case(self, case_id, *, actor, expected_case_version, request_id, idempotency_key):
        return self._case_lifecycle(case_id, operation="start", actor=actor,
            expected_case_version=expected_case_version, request_id=request_id,
            idempotency_key=idempotency_key, reason="processor started work")

    def request_applicant(self, case_id, *, actor, expected_case_version, request_id, idempotency_key, reason):
        return self._case_lifecycle(case_id, operation="wait", actor=actor,
            expected_case_version=expected_case_version, request_id=request_id,
            idempotency_key=idempotency_key, reason=reason)

    def resume_case(self, case_id, *, actor, claim_version, decision_hash, expected_case_version,
                    request_id, idempotency_key, evidence_ref, reason, routing):
        """Applicant explicitly requeues supplemental evidence; never reruns business work.

        Core Claim/attachment changes require a new Claim version and routing instead.
        Frozen deadlines and breach markers do not pause or reset while waiting.
        """
        return self._case_lifecycle(case_id, operation="resume", actor=actor,
            claim_version=claim_version, decision_hash=decision_hash, evidence_ref=evidence_ref,
            expected_case_version=expected_case_version, request_id=request_id,
            idempotency_key=idempotency_key, reason=reason, routing=routing)

    def resolve_case(self, case_id, *, actor, decision, approval_id, claim_version, decision_hash,
                     expected_case_version, request_id, idempotency_key, reason):
        """Approve/reject through S5, or complete human work without any Claim write.

        A repeated resolve fails closed, even for the same idempotency key. An
        initially unbound case may bind an EXISTING matching pending review here.
        """
        from .case_store import _token
        _token(request_id, "request_id")
        _token(idempotency_key, "idempotency_key", limit=180)
        reason = self._reason(reason)
        if decision not in {"approve", "reject", "complete"}:
            raise ExpenseStoreError("invalid_decision", "case decision must be approve, reject, or complete")
        if approval_id is not None:
            _token(approval_id, "approval_id", limit=128)
        with self._transaction() as connection:
            row, claim = self._operation_row(connection, case_id)
            self._authorize(connection, row, actor)
            state = self._work_state(connection, row, ensure=True)
            self._process_access(actor, json.loads(state["queue_json"]), row)
            if row["status"] in TERMINAL_STATUSES:
                raise ExpenseStoreError("invalid_case_transition", "terminal case cannot resolve again")
            self._case_version(state, expected_case_version)
            self._case_binding(connection, row, claim, claim_version=claim_version, decision_hash=decision_hash)
            self._owned_case(row, state, actor)
            if row["status"] != "in_progress":
                raise ExpenseStoreError("invalid_case_transition", "resolution requires in_progress")
            if connection.execute(select(self._actions.c.case_id).where(self._actions.c.case_id == case_id,
                    self._actions.c.idempotency_key == idempotency_key)).first():
                raise ExpenseStoreError("idempotency_conflict", "case action key already used")
            previous_approval = row["approval_id"]
            if previous_approval is not None and previous_approval != approval_id:
                raise ExpenseStoreError("approval_binding_mismatch", "case already has a different approval binding")
            context = dict(case_id=case_id, expected_case_version=expected_case_version)
            review = None
            if decision in {"approve", "reject"}:
                if actor.role not in {Role.FINANCE_REVIEWER, Role.FINANCE_ADMIN}:
                    raise ExpenseStoreError("permission_denied", "Expense approval role required", status_code=403)
                if not approval_id:
                    raise ExpenseStoreError("approval_binding_mismatch", "existing Expense approval required")
                self._claims_store._pending_review(connection, approval_id, claim_id=row["claim_id"],
                    expected_version=claim_version, decision_hash=decision_hash)
                try:
                    review = resolve_review(approval_id, decision=decision, approver_id=actor.actor_id,
                        claim_id=row["claim_id"], expected_version=claim_version, decision_hash=decision_hash,
                        request_id=request_id, idempotency_key=f"case:{case_id}:{expected_case_version}",
                        comment=reason, case_context=context,
                        store=_ReviewTransaction(self._claims_store, connection))
                except ReviewError as exc:
                    raise ExpenseStoreError(exc.code, str(exc), status_code=exc.status_code) from exc
                row["approval_id"] = approval_id
                connection.execute(self._cases.update().where(self._cases.c.case_id == case_id).values(approval_id=approval_id))
            else:
                # Complete may never sneak in a new unvalidated approval binding.
                if approval_id != previous_approval:
                    raise ExpenseStoreError("approval_binding_mismatch", "complete must preserve the case approval binding")
                blocked = permission_block_message("case.resolve", {**context, "claim_id": row["claim_id"],
                    "claim_version": claim_version, "decision_hash": decision_hash, "approval_id": approval_id,
                    "decision": decision, "actor_id": actor.actor_id, "reason": reason}, require_bound_approval=True)
                if blocked:
                    raise ExpenseStoreError("permission_denied", blocked, status_code=403)
            self._change(connection, row, state, actor=actor, request_id=request_id,
                event_type="case_resolved", reason=reason, status="resolved",
                notify=True,
                state_changes={"assignee_id": None, "lock_expires_at": None},
                metadata={"decision": decision, "approval_id": approval_id, "previous_approval_id": previous_approval,
                    "claim_version": claim_version, "decision_hash": decision_hash,
                    "claim_status_before": claim["status"],
                    "claim_status_after": review["status"] if review else claim["status"],
                    "claim_changed": review is not None})
            result = self._case_result(connection, row)
            self._save_case_action(connection, row, state, actor=actor, key=idempotency_key,
                fingerprint=_fingerprint(dict(context, decision=decision, approval_id=approval_id,
                    claim_version=claim_version, decision_hash=decision_hash, reason=reason)), result=result)
            return result
