"""SQL case/event/outbox storage sharing the formal Claim database.

H3 composes case resolution with the existing Expense approval transaction.
Actors and queue memberships must be supplied by a trusted caller, never headers.
"""
from __future__ import annotations

import json
import re
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from sqlalchemy import (
    CheckConstraint, Column, DDL, DateTime, ForeignKey, ForeignKeyConstraint,
    Integer, String, Table, Text, UniqueConstraint, event, func, select,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .domain import ContractError, Decision
from .case_operations import CaseOperations
from .case_resolution import CaseResolution
from .notifications import NotificationStorage
from .case_metrics import CaseMetrics
from .sla import utc
from .handoff import (
    CaseStatus, HandoffError, QueueId, ReasonCode, Role, RoutingConfig, TERMINAL_STATUSES,
    plan_handoff,
)
from .store import ExpenseClaimStore, ExpenseStoreError, _fingerprint, _json


@dataclass(frozen=True)
class CaseActor:
    """Trusted application identity; this is not authentication or a membership directory."""
    actor_id: str
    role: Role = Role.APPLICANT
    queue_ids: tuple[QueueId, ...] = ()

    def __post_init__(self):
        if not isinstance(self.actor_id, str) or not self.actor_id.strip() or len(self.actor_id) > 200:
            raise ExpenseStoreError("case_not_found", "expense case not found", status_code=404)
        try:
            object.__setattr__(self, "role", Role(self.role))
            object.__setattr__(self, "queue_ids", tuple(QueueId(q) for q in self.queue_ids))
        except (ValueError, TypeError) as exc:
            raise ExpenseStoreError("queue_not_allowed", "invalid case identity scope", status_code=403) from exc


def _timestamp(value: datetime) -> str:
    return value.replace(tzinfo=value.tzinfo or timezone.utc).isoformat().replace("+00:00", "Z")


def _token(value: str, name: str, *, limit: int = 200) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]+", value) or len(value) > limit:
        raise ExpenseStoreError("invalid_handoff", f"{name} must be an opaque identifier (max {limit})", status_code=400)
    return value


class ExpenseCaseStore(CaseMetrics, NotificationStorage, CaseResolution, CaseOperations):
    """Use the Claim store's engine, tables and transaction boundary; SQLite is for tests."""

    def __init__(self, claims: ExpenseClaimStore, *, clock: Callable[[], datetime] | None = None,
                 claim_lock_seconds: int = 900):
        if type(claim_lock_seconds) is not int or not 1 <= claim_lock_seconds <= 86400:
            raise ExpenseStoreError("invalid_handoff", "claim lock must be between 1 and 86400 seconds", status_code=400)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._claim_lock_seconds = claim_lock_seconds
        self._claims_store = claims
        self._engine = claims._engine
        metadata = claims._metadata
        # Reuse tables if another adapter is attached to the same Claim store.
        if "expense_cases" in metadata.tables:
            self._cases = metadata.tables["expense_cases"]
            self._events = metadata.tables["expense_case_events"]
            self._outbox = metadata.tables["expense_case_outbox"]
            self._init_operations(metadata)
            self._init_notifications(metadata)
            metadata.create_all(self._engine, checkfirst=True)
            return
        self._cases = Table(
            "expense_cases", metadata,
            Column("case_id", String(128), primary_key=True),
            Column("claim_id", String(128), nullable=False),
            Column("claim_version", Integer, nullable=False),
            Column("decision_hash", String(200), nullable=False),
            Column("reason_code", String(80), nullable=False),
            Column("approval_id", String(128), ForeignKey(claims._reviews.c.approval_id)),
            Column("status", String(32), nullable=False),
            Column("queue_id", String(80)),
            Column("priority", String(16), nullable=False),
            Column("routing_rule_version", String(200), nullable=False),
            Column("snapshot_json", Text, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("source_request_id", String(200), nullable=False),
            UniqueConstraint("claim_id", "claim_version", "reason_code", name="uq_expense_case_trigger"),
            ForeignKeyConstraint(["claim_id", "claim_version"], [claims._versions.c.claim_id, claims._versions.c.version]),
            ForeignKeyConstraint(["claim_id", "claim_version"], [claims._decisions.c.claim_id, claims._decisions.c.version]),
            CheckConstraint("claim_version > 0"),
            CheckConstraint("status IN (" + ",".join(f"'{s}'" for s in CaseStatus) + ")"),
            CheckConstraint("reason_code IN (" + ",".join(f"'{r}'" for r in ReasonCode) + ")"),
            CheckConstraint("queue_id IS NULL OR queue_id IN ('finance_review','finance_admin','expense_operations')"),
            CheckConstraint("priority IN ('urgent','high','normal','low')"),
        )
        self._events = Table(
            "expense_case_events", metadata,
            Column("event_id", String(128), primary_key=True),
            Column("case_id", String(128), ForeignKey(self._cases.c.case_id), nullable=False),
            Column("sequence", Integer, nullable=False),
            Column("event_key", String(200), nullable=False),
            Column("fingerprint", String(200), nullable=False),
            Column("event_type", String(80), nullable=False),
            Column("from_status", String(32)),
            Column("to_status", String(32), nullable=False),
            Column("actor_type", String(32), nullable=False),
            Column("actor_id", String(200), nullable=False),
            Column("queue_id", String(80)),
            Column("claim_version", Integer, nullable=False),
            Column("request_id", String(200), nullable=False),
            Column("metadata_json", Text, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            UniqueConstraint("case_id", "event_key", name="uq_expense_case_event_key"),
            UniqueConstraint("case_id", "sequence", name="uq_expense_case_event_sequence"),
            CheckConstraint("sequence > 0"),
        )
        self._outbox = Table(
            "expense_case_outbox", metadata,
            Column("outbox_id", String(128), primary_key=True),
            Column("case_id", String(128), ForeignKey(self._cases.c.case_id), nullable=False),
            Column("event_id", String(128), ForeignKey(self._events.c.event_id), nullable=False, unique=True),
            Column("notification_type", String(80), nullable=False),
            Column("target_queue", String(80), nullable=False),
            Column("status", String(32), nullable=False),
            Column("payload_json", Text, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            CheckConstraint("status = 'pending'"),  # Immutable intent; delivery lifecycle lives separately.
        )
        self._install_append_only_ddl()
        self._init_operations(metadata)
        self._init_notifications(metadata)
        metadata.create_all(self._engine, checkfirst=True)

    def _now(self):
        return utc(self._clock())

    def _install_append_only_ddl(self):
        # Database enforcement, not merely the absence of Python update/delete methods.
        event.listen(self._events, "after_create", DDL("""
            CREATE FUNCTION expense_case_event_append_only() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN
                RAISE EXCEPTION 'expense_case_events is append-only';
            END $$
        """).execute_if(dialect="postgresql"))
        event.listen(self._events, "after_create", DDL("""
            CREATE TRIGGER expense_case_event_immutable
            BEFORE UPDATE OR DELETE OR TRUNCATE ON expense_case_events
            FOR EACH STATEMENT EXECUTE FUNCTION expense_case_event_append_only()
        """).execute_if(dialect="postgresql"))
        for operation in ("UPDATE", "DELETE"):
            event.listen(self._events, "after_create", DDL(f"""
                CREATE TRIGGER expense_case_event_no_{operation.lower()}
                BEFORE {operation} ON expense_case_events BEGIN
                    SELECT RAISE(ABORT, 'expense_case_events is append-only');
                END
            """).execute_if(dialect="sqlite"))

    @contextmanager
    def _transaction(self):
        with self._engine.connect() as connection:
            if self._engine.dialect.name == "sqlite":
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                connection.begin()
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def _locked(self, statement):
        return statement.with_for_update() if self._engine.dialect.name == "postgresql" else statement

    @staticmethod
    def _not_found():
        return ExpenseStoreError("case_not_found", "expense case not found", status_code=404)

    def _authorize(self, connection, row, actor: CaseActor, *, processing: bool = False):
        if row is None:
            raise self._not_found()
        claim = connection.execute(select(self._claims_store._claims).where(
            self._claims_store._claims.c.claim_id == row["claim_id"]
        )).mappings().first()
        if claim is None:
            raise self._not_found()
        if actor.role == Role.FINANCE_ADMIN:
            return
        if actor.role == Role.APPLICANT:
            if claim["applicant_id"] == actor.actor_id and not processing:
                return
        else:
            queue = json.loads(self._work_state(connection, row)["queue_json"])
            if queue and row["queue_id"] in actor.queue_ids and actor.role in queue["allowed_roles"]:
                return
            if (row["status"] == "unrouted" and actor.role == Role.EXPENSE_OPERATOR
                    and QueueId.EXPENSE_OPERATIONS in actor.queue_ids):
                return
        raise self._not_found()

    def _case_result(self, connection, row, *, replay=False):
        snapshot = json.loads(row["snapshot_json"])
        state = self._work_state(connection, row)
        dates = {key: _timestamp(state[key]) if state[key] else None for key in
                 ("lock_expires_at", "responded_at", "response_due_at", "resolution_due_at")}
        return {**snapshot, "case_id": row["case_id"], "status": row["status"],
                "initial_queue_id": snapshot["queue_id"],
                "initial_routing_rule_version": snapshot["routing_rule_version"],
                "queue_id": row["queue_id"], "priority": row["priority"],
                "queue_definition": json.loads(state["queue_json"]), "sla": json.loads(state["sla_json"]),
                "routing_rule_version": state["routing_rule_version"], "error_code": state["routing_error"],
                **{key: state[key] for key in ("case_version", "assignee_id", "response_breached",
                    "resolution_breached", "escalation_level")}, **dates,
                "approval_id": row["approval_id"], "created_at": _timestamp(row["created_at"]),
                "source_request_id": row["source_request_id"], "idempotent_replay": replay}

    def create(
        self, claim_id: str, *, claim_version: int, decision_hash: str, actor: CaseActor,
        routing: RoutingConfig, request_id: str, approval_id: str | None = None,
    ) -> dict[str, Any]:
        """Create from the stored Decision, never from a client-authored route/assignee."""
        _token(request_id, "request_id")
        if type(claim_version) is not int or claim_version < 1:
            raise ExpenseStoreError("claim_version_mismatch", "positive Claim version required")
        with self._transaction() as connection:
            claim = self._claims_store._get_claim_row(connection, claim_id, lock=True)
            if claim is None or not (actor.role == Role.FINANCE_ADMIN or
                    (actor.role == Role.APPLICANT and claim["applicant_id"] == actor.actor_id)):
                raise self._not_found()
            if claim["current_version"] != claim_version:
                raise ExpenseStoreError("claim_version_mismatch", "Claim version changed")
            stored = connection.execute(select(self._claims_store._decisions).where(
                self._claims_store._decisions.c.claim_id == claim_id,
                self._claims_store._decisions.c.version == claim_version,
            )).mappings().first()
            if stored is None:
                raise ExpenseStoreError("invalid_handoff", "persisted Decision is required")
            if stored["decision_hash"] != decision_hash:
                raise ExpenseStoreError("idempotency_conflict", "Decision fingerprint differs")
            try:
                decision = Decision.from_dict(json.loads(stored["decision_json"]))
                if (decision.claim_id, decision.claim_version, decision.decision_hash) != (claim_id, claim_version, decision_hash):
                    raise ContractError("persisted Decision binding differs")
                # H0 may reject compatibility/free-text reasons; never rewrite a decision hash.
                reason = ReasonCode(decision.handoff.reason_code) if decision.handoff else None
            except (ContractError, ValueError, TypeError) as exc:
                raise ExpenseStoreError("invalid_handoff", "invalid persisted handoff Decision") from exc
            if approval_id is not None:
                approval = connection.execute(select(self._claims_store._reviews).where(
                    self._claims_store._reviews.c.approval_id == approval_id
                )).mappings().first()
                if approval is None or (approval["claim_id"], approval["claim_version"], approval["decision_hash"]) != (claim_id, claim_version, decision_hash):
                    raise ExpenseStoreError("approval_binding_mismatch", "approval does not match Claim/version/hash")
            existing = connection.execute(select(self._cases).where(
                self._cases.c.claim_id == claim_id, self._cases.c.claim_version == claim_version,
                self._cases.c.reason_code == reason,
            )).mappings().first()
            if existing is not None:
                return self._reuse(connection, existing, decision_hash, approval_id)
            try:
                plan = plan_handoff(decision, routing)
            except HandoffError as exc:
                raise ExpenseStoreError(str(exc.code), str(exc)) from exc
            if plan is None:
                raise ExpenseStoreError("invalid_handoff", "Decision does not require a case")
            snapshot = asdict(plan)
            snapshot.pop("case_id")
            snapshot["idempotency_key"] = plan.idempotency_key
            snapshot["queue_definition"] = next((asdict(q) for q in routing.queues if q.queue_id == plan.queue_id), None)
            now = self._now()
            case_id = "case_" + uuid.uuid4().hex
            insert = pg_insert if self._engine.dialect.name == "postgresql" else sqlite_insert
            inserted = connection.execute(insert(self._cases).values(
                case_id=case_id, claim_id=claim_id, claim_version=claim_version, decision_hash=decision_hash,
                reason_code=plan.reason_code, approval_id=approval_id, status=plan.status, queue_id=plan.queue_id,
                priority=plan.priority, routing_rule_version=plan.routing_rule_version, snapshot_json=_json(snapshot),
                created_at=now, source_request_id=request_id,
            ).on_conflict_do_nothing(index_elements=["claim_id", "claim_version", "reason_code"]).returning(self._cases.c.case_id)).scalar_one_or_none()
            if inserted is None:
                winner = connection.execute(select(self._cases).where(
                    self._cases.c.claim_id == claim_id, self._cases.c.claim_version == claim_version,
                    self._cases.c.reason_code == plan.reason_code,
                )).mappings().one()
                return self._reuse(connection, winner, decision_hash, approval_id)
            row = connection.execute(select(self._cases).where(self._cases.c.case_id == case_id)).mappings().one()
            self._work_state(connection, row, ensure=True)
            event_id = self._append(connection, row, event_key="case_created", event_type="case_created",
                actor=actor, request_id=request_id, metadata={"decision_hash": decision_hash,
                    "approval_id": approval_id, "routing_rule_version": plan.routing_rule_version,
                    "claim_id": claim_id, "claim_version": claim_version}, created=True)
            connection.execute(self._outbox.insert().values(
                outbox_id="out_" + uuid.uuid4().hex, case_id=case_id, event_id=event_id,
                notification_type="case_created" if plan.queue_id else "case_unrouted",
                target_queue=plan.queue_id or QueueId.EXPENSE_OPERATIONS, status="pending",
                payload_json=_json({"case_id": case_id, "event_id": event_id}), created_at=now,
            ))
            return self._case_result(connection, row)

    def _reuse(self, connection, row, decision_hash, approval_id):
        if row["decision_hash"] != decision_hash or row["approval_id"] != approval_id:
            raise ExpenseStoreError("idempotency_conflict", "trigger has a different Decision/approval binding")
        if row["status"] in TERMINAL_STATUSES:
            raise ExpenseStoreError("case_already_exists", "terminal case cannot be reopened")
        return self._case_result(connection, row, replay=True)

    def get(self, case_id: str, *, actor: CaseActor) -> dict[str, Any]:
        with self._engine.connect() as connection:
            row = connection.execute(select(self._cases).where(self._cases.c.case_id == case_id)).mappings().first()
            self._authorize(connection, row, actor)
            return self._case_result(connection, row)

    def list_cases(self, *, actor: CaseActor) -> list[dict[str, Any]]:
        with self._engine.connect() as connection:
            # Scope in SQL before loading snapshots; queue roles are checked again against each snapshot.
            statement = select(self._cases).join(self._claims_store._claims,
                self._cases.c.claim_id == self._claims_store._claims.c.claim_id)
            if actor.role == Role.APPLICANT:
                statement = statement.where(self._claims_store._claims.c.applicant_id == actor.actor_id)
            elif actor.role != Role.FINANCE_ADMIN:
                from sqlalchemy import or_
                statement = statement.where(or_(self._cases.c.queue_id.in_(actor.queue_ids),
                    (self._cases.c.status == "unrouted") if actor.role == Role.EXPENSE_OPERATOR
                    and QueueId.EXPENSE_OPERATIONS in actor.queue_ids else False))
            results = []
            for row in connection.execute(statement.order_by(self._cases.c.created_at, self._cases.c.case_id)).mappings():
                try:
                    self._authorize(connection, row, actor)
                except ExpenseStoreError:
                    continue
                results.append(self._case_result(connection, row))
            return results

    def _append(self, connection, row, *, event_key, event_type, actor, request_id, metadata,
                created=False, from_status=None):
        sequence = connection.execute(select(func.coalesce(func.max(self._events.c.sequence), 0)).where(
            self._events.c.case_id == row["case_id"])).scalar_one() + 1
        event_id = "cev_" + uuid.uuid4().hex
        connection.execute(self._events.insert().values(
            event_id=event_id, case_id=row["case_id"], sequence=sequence, event_key=event_key,
            fingerprint=_fingerprint({"event_type": event_type, "actor_id": actor.actor_id,
                "actor_type": actor.role, "metadata": metadata}),
            event_type=event_type, from_status=None if created else (from_status or row["status"]), to_status=row["status"],
            actor_type=actor.role, actor_id=actor.actor_id, queue_id=row["queue_id"],
            claim_version=row["claim_version"], request_id=request_id, metadata_json=_json(metadata),
            created_at=self._now(),
        ))
        return event_id

    def append_event(self, case_id: str, *, actor: CaseActor, request_id: str,
                     idempotency_key: str, evidence_ref: str) -> dict[str, Any]:
        """Append an opaque evidence reference; no arbitrary status events or secret payloads."""
        _token(request_id, "request_id")
        _token(idempotency_key, "idempotency_key", limit=180)
        _token(evidence_ref, "evidence_ref", limit=128)
        key = "evidence:" + idempotency_key
        metadata = {"evidence_ref": evidence_ref}
        fingerprint = _fingerprint({"event_type": "evidence_recorded", "actor_id": actor.actor_id,
            "actor_type": actor.role, "metadata": metadata})
        with self._transaction() as connection:
            row = connection.execute(self._locked(select(self._cases).where(self._cases.c.case_id == case_id))).mappings().first()
            self._authorize(connection, row, actor)
            existing = connection.execute(select(self._events).where(
                self._events.c.case_id == case_id, self._events.c.event_key == key)).mappings().first()
            if existing is not None:
                if existing["fingerprint"] != fingerprint:
                    raise ExpenseStoreError("idempotency_conflict", "event key payload differs")
                return self._event_result(existing, replay=True)
            if row["status"] in TERMINAL_STATUSES:
                raise ExpenseStoreError("invalid_case_transition", "terminal case cannot accept new evidence")
            event_id = self._append(connection, row, event_key=key, event_type="evidence_recorded",
                actor=actor, request_id=request_id, metadata=metadata)
            stored = connection.execute(select(self._events).where(self._events.c.event_id == event_id)).mappings().one()
            return self._event_result(stored)

    @staticmethod
    def _event_result(row, *, replay=False):
        result = dict(row)
        result.pop("fingerprint")
        result["metadata"] = json.loads(result.pop("metadata_json"))
        result["created_at"] = _timestamp(result["created_at"])
        result["idempotent_replay"] = replay
        return result

    def events(self, case_id: str, *, actor: CaseActor) -> list[dict[str, Any]]:
        with self._engine.connect() as connection:
            row = connection.execute(select(self._cases).where(self._cases.c.case_id == case_id)).mappings().first()
            self._authorize(connection, row, actor)
            return [self._event_result(e) for e in connection.execute(select(self._events).where(
                self._events.c.case_id == case_id).order_by(self._events.c.sequence)).mappings()]

    def outbox(self, case_id: str, *, actor: CaseActor) -> list[dict[str, Any]]:
        """Read original pending intents; delivery progress is deliberately separate."""
        with self._engine.connect() as connection:
            row = connection.execute(select(self._cases).where(self._cases.c.case_id == case_id)).mappings().first()
            self._authorize(connection, row, actor, processing=True)
            results = []
            for item in connection.execute(select(self._outbox).where(self._outbox.c.case_id == case_id)
                    .order_by(self._outbox.c.created_at, self._outbox.c.outbox_id)).mappings():
                result = dict(item)
                result["payload"] = json.loads(result.pop("payload_json"))
                result["created_at"] = _timestamp(result["created_at"])
                results.append(result)
            return results
