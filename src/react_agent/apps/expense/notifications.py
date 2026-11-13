"""H4 local-only outbox delivery. Acceptance is neither reading nor approval.

Original intents and business events survive all retries. A worker crash can
repeat an adapter call, so adapters must deduplicate the stable outbox ID.
No HTTP, external transport, automatic scheduling or Claim/approval writes.
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import Protocol

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Table, Text, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .handoff import Role
from .sla import utc
from .store import ExpenseStoreError, _fingerprint, _json


def notification_kind(source: str) -> str:
    if source == "case_claimed":
        return "case_assigned"
    if source == "case_needs_applicant":
        return "needs_applicant"
    if source.startswith("sla_"):
        if source.endswith("_warning"):
            return "sla_warning"
        if source.endswith("_breached"):
            return "sla_breached"
    return source


@dataclass(frozen=True)
class Notification:
    outbox_id: str
    case_id: str
    event_id: str
    notification_type: str
    recipients: tuple[str, ...]


@dataclass(frozen=True)
class DeliveryResult:
    delivery_id: str | None
    status: str
    error: str | None


class NotificationAdapter(Protocol):
    # This slice only permits trusted local implementations, never outbound IO.
    local_only: bool

    def deliver(self, notification: Notification) -> DeliveryResult: ...


class LocalNotificationAdapter:
    """Durable local receipt, idempotent across adapter/worker restarts.

    No recipient directory or real mailbox is connected. This records local
    acceptance only, with deliberately no 'read' or 'notified person' status.
    """
    local_only = True

    def __init__(self, store):
        self.store = store

    def deliver(self, notification: Notification) -> DeliveryResult:
        store = self.store
        table = store._local_receipts
        payload = _json(asdict(notification))
        fingerprint = _fingerprint(asdict(notification))
        insert = pg_insert if store._engine.dialect.name == "postgresql" else sqlite_insert
        with store._transaction() as connection:
            connection.execute(insert(table).values(outbox_id=notification.outbox_id,
                delivery_id="local_" + uuid.uuid4().hex, fingerprint=fingerprint,
                payload_json=payload, created_at=store._now()).on_conflict_do_nothing(index_elements=["outbox_id"]))
            receipt = connection.execute(select(table).where(table.c.outbox_id == notification.outbox_id)).mappings().one()
            if receipt["fingerprint"] != fingerprint:
                return DeliveryResult(None, "failed", "adapter_idempotency_conflict")
            return DeliveryResult(receipt["delivery_id"], "accepted", None)


class NotificationStorage:
    def _init_notifications(self, metadata):
        if "expense_notification_delivery" in metadata.tables:
            self._deliveries = metadata.tables["expense_notification_delivery"]
            self._local_receipts = metadata.tables["expense_local_notification_receipts"]
            return
        self._deliveries = Table(
            "expense_notification_delivery", metadata,
            Column("outbox_id", String(128), ForeignKey(self._outbox.c.outbox_id), primary_key=True),
            Column("status", String(32), nullable=False),
            Column("attempt", Integer, nullable=False),
            Column("lease_token", String(128)),
            Column("lease_until", DateTime(timezone=True)),
            Column("next_attempt_at", DateTime(timezone=True)),
            Column("delivery_id", String(200)),
            Column("error", String(80)),
            CheckConstraint("attempt > 0"),
            CheckConstraint("status IN ('processing','retry_wait','accepted')"),
            CheckConstraint("(status = 'processing' AND lease_token IS NOT NULL AND lease_until IS NOT NULL) OR "
                            "(status <> 'processing' AND lease_token IS NULL AND lease_until IS NULL)"),
        )
        self._local_receipts = Table(
            "expense_local_notification_receipts", metadata,
            Column("outbox_id", String(128), ForeignKey(self._outbox.c.outbox_id), primary_key=True),
            Column("delivery_id", String(200), nullable=False, unique=True),
            Column("fingerprint", String(200), nullable=False),
            Column("payload_json", Text, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
        )

    @staticmethod
    def _notification_admin(actor):
        if actor.role != Role.FINANCE_ADMIN:
            raise ExpenseStoreError("queue_not_allowed", "trusted maintenance role required", status_code=403)

    def delivery_status(self, case_id, *, actor):
        """Authorized processing read; original outbox() remains the intent log."""
        from .case_store import _timestamp
        with self._engine.connect() as connection:
            row = connection.execute(select(self._cases).where(self._cases.c.case_id == case_id)).mappings().first()
            self._authorize(connection, row, actor, processing=True)
            records = connection.execute(select(self._outbox.c.outbox_id, self._deliveries.c.status,
                self._deliveries.c.attempt, self._deliveries.c.delivery_id, self._deliveries.c.error,
                self._deliveries.c.next_attempt_at, self._deliveries.c.lease_until).select_from(
                    self._outbox.outerjoin(self._deliveries)).where(self._outbox.c.case_id == case_id)
                .order_by(self._outbox.c.created_at, self._outbox.c.outbox_id)).mappings()
            return [{**dict(r), "status": r["status"] or "pending", "attempt": r["attempt"] or 0,
                     "next_attempt_at": _timestamp(r["next_attempt_at"]) if r["next_attempt_at"] else None,
                     "lease_until": _timestamp(r["lease_until"]) if r["lease_until"] else None,
                     "user_read": False} for r in records]

    def _notification(self, connection, intent):
        source = connection.execute(select(self._events).where(self._events.c.event_id == intent["event_id"],
            self._events.c.case_id == intent["case_id"])).mappings().one()
        kind = notification_kind(intent["notification_type"])
        metadata = json.loads(source["metadata_json"])
        if kind == "case_assigned":
            assignee = metadata.get("assignee_id")
            if not assignee:
                raise ExpenseStoreError("invalid_handoff", "source event missing assignee")
            recipients = ("actor:" + assignee,)
        elif kind in {"needs_applicant", "case_resolved"}:
            applicant = connection.execute(select(self._claims_store._claims.c.applicant_id).join(
                self._cases, self._cases.c.claim_id == self._claims_store._claims.c.claim_id).where(
                    self._cases.c.case_id == intent["case_id"])).scalar_one()
            recipients = ("actor:" + applicant,)
            if kind == "case_resolved":
                recipients += ("observers:" + intent["target_queue"],)
        else:
            prefix = "queue_owner:" if kind in {"sla_warning", "sla_breached"} else "queue:"
            recipients = (prefix + intent["target_queue"],)
        return Notification(intent["outbox_id"], intent["case_id"], intent["event_id"], kind, recipients)

    def _notification_audit(self, connection, row, *, actor, outbox_id, attempt, phase, metadata):
        return self._append(connection, row, event_key=f"notify:{outbox_id}:{attempt}:{phase}",
            event_type="notification_" + phase, actor=actor, request_id="notification-worker",
            metadata={"outbox_id": outbox_id, "attempt": attempt, **metadata})

    def _reserve_notification(self, outbox_id, *, actor, lease_seconds):
        with self._transaction() as connection:
            intent = connection.execute(select(self._outbox).where(self._outbox.c.outbox_id == outbox_id)).mappings().one()
            # Consistent with H1-H3: Claim -> case -> delivery. No locks during IO.
            row, _ = self._operation_row(connection, intent["case_id"])
            state = connection.execute(self._locked(select(self._deliveries).where(
                self._deliveries.c.outbox_id == outbox_id))).mappings().first()
            now = self._now()
            if state:
                if state["status"] == "accepted":
                    return None
                if state["status"] == "processing":
                    if utc(state["lease_until"]) > now:
                        return None
                    self._notification_audit(connection, row, actor=actor, outbox_id=outbox_id,
                        attempt=state["attempt"], phase="lease_expired", metadata={"error": "delivery_outcome_unknown"})
                elif utc(state["next_attempt_at"]) > now:
                    return None
            attempt = state["attempt"] + 1 if state else 1
            token = uuid.uuid4().hex
            values = dict(status="processing", attempt=attempt, lease_token=token,
                          lease_until=now + timedelta(seconds=lease_seconds), next_attempt_at=None,
                          delivery_id=None, error=None)
            if state:
                connection.execute(self._deliveries.update().where(self._deliveries.c.outbox_id == outbox_id).values(**values))
            else:
                connection.execute(self._deliveries.insert().values(outbox_id=outbox_id, **values))
            self._notification_audit(connection, row, actor=actor, outbox_id=outbox_id,
                attempt=attempt, phase="attempt_started", metadata={})
            return dict(intent), token, attempt

    def _finish_notification(self, intent, token, attempt, result, *, actor, retry_seconds):
        with self._transaction() as connection:
            row, _ = self._operation_row(connection, intent["case_id"])
            state = connection.execute(self._locked(select(self._deliveries).where(
                self._deliveries.c.outbox_id == intent["outbox_id"]))).mappings().one()
            if state["lease_token"] != token or state["status"] != "processing" or utc(state["lease_until"]) <= self._now():
                return False  # A stale worker cannot overwrite a newer delivery outcome.
            accepted = result.status == "accepted"
            retry_at = None if accepted else self._now() + timedelta(seconds=retry_seconds)
            connection.execute(self._deliveries.update().where(self._deliveries.c.outbox_id == intent["outbox_id"]).values(
                status="accepted" if accepted else "retry_wait", lease_token=None, lease_until=None,
                next_attempt_at=retry_at, delivery_id=result.delivery_id, error=result.error))
            self._notification_audit(connection, row, actor=actor, outbox_id=intent["outbox_id"],
                attempt=attempt, phase="attempt_finished", metadata={"status": result.status,
                    "delivery_id": result.delivery_id, "error": result.error,
                    "next_attempt_at": retry_at.isoformat() if retry_at else None, "user_read": False})
            return True


def _safe_result(result):
    # Do not retain exception strings, free text, credentials or arbitrary objects.
    def opaque(value, size):
        return isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z0-9_.:-]{1," + str(size) + r"}", value))
    if isinstance(result, DeliveryResult):
        if result.status == "accepted" and opaque(result.delivery_id, 200) and result.error is None:
            return result
        if (result.status == "failed" and opaque(result.error, 80) and
                (result.delivery_id is None or opaque(result.delivery_id, 200))):
            return result
    return DeliveryResult(None, "failed", "adapter_invalid_result")


class OutboxWorker:
    """Explicit bounded run_once; no background service or outbound transport."""

    def __init__(self, store, adapter: NotificationAdapter, *, actor, lease_seconds=60,
                 retry_base_seconds=5, retry_max_seconds=3600):
        store._notification_admin(actor)
        if getattr(adapter, "local_only", False) is not True:
            raise ValueError("H4 only supports trusted local notification adapters")
        if (any(type(n) is not int or n < 1 for n in (lease_seconds, retry_base_seconds, retry_max_seconds)) or
                lease_seconds > 86400 or not retry_base_seconds <= retry_max_seconds <= 86400):
            raise ValueError("invalid notification lease/retry configuration")
        self.store, self.adapter, self.actor = store, adapter, actor
        self.lease_seconds, self.retry_base, self.retry_max = lease_seconds, retry_base_seconds, retry_max_seconds

    def run_once(self, *, limit=100):
        self.store._notification_admin(self.actor)
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("notification limit must be 1..1000")
        store = self.store
        delivery = store._deliveries
        with store._engine.connect() as connection:
            ids = connection.execute(select(store._outbox.c.outbox_id).select_from(store._outbox.outerjoin(delivery))
                .where(or_(delivery.c.outbox_id.is_(None),
                    (delivery.c.status == "retry_wait") & (delivery.c.next_attempt_at <= store._now()),
                    (delivery.c.status == "processing") & (delivery.c.lease_until <= store._now())))
                .order_by(store._outbox.c.created_at, store._outbox.c.outbox_id).limit(limit)).scalars().all()
        results = []
        for outbox_id in ids:
            reserved = store._reserve_notification(outbox_id, actor=self.actor, lease_seconds=self.lease_seconds)
            if reserved is None:
                continue
            intent, token, attempt = reserved
            try:
                with store._engine.connect() as connection:
                    notification = store._notification(connection, intent)
                result = _safe_result(self.adapter.deliver(notification))
            except Exception:
                result = DeliveryResult(None, "failed", "adapter_exception")
            # Clamp before exponentiation: unbounded retries must not build huge ints.
            retry_seconds = min(self.retry_max, self.retry_base * (2 ** min(attempt - 1, 17)))
            saved = store._finish_notification(intent, token, attempt, result,
                actor=self.actor, retry_seconds=retry_seconds)
            results.append({"outbox_id": outbox_id, **asdict(result), "recorded": saved, "user_read": False})
        return results
