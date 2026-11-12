"""SQLAlchemy-backed persistence for the formal Expense Claim lifecycle."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    create_engine,
    select,
    update,
)
from sqlalchemy.engine import Engine

from .domain import Decision, Handoff


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


class ExpenseStoreError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 409):
        self.code = code
        self.status_code = status_code
        super().__init__(message)


class ExpenseClaimStore:
    """Persist formal claims while keeping ExpenseLedger as a legacy adapter."""

    def __init__(self, url: str | None = None, *, engine: Engine | None = None):
        resolved = url or os.environ.get("REACT_AGENT_DATABASE_URL") or os.environ.get("REACT_AGENT_POSTGRES_URL")
        if engine is None and not resolved:
            raise ValueError("REACT_AGENT_DATABASE_URL or REACT_AGENT_POSTGRES_URL is required")
        self._engine = engine or create_engine(resolved, pool_pre_ping=True)
        if self._engine.dialect.name not in {"postgresql", "sqlite"}:
            raise ValueError("Expense Claim storage requires PostgreSQL or SQLite")
        self._metadata = MetaData()
        self._claims = Table(
            "expense_claims",
            self._metadata,
            Column("claim_id", String(128), primary_key=True),
            Column("applicant_id", String(200), nullable=False),
            Column("current_version", Integer, nullable=False),
            Column("status", String(32), nullable=False),
            Column("claim_json", Text, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
        )
        self._versions = Table(
            "expense_claim_versions",
            self._metadata,
            Column("claim_id", String(128), nullable=False),
            Column("version", Integer, nullable=False),
            Column("status", String(32), nullable=False),
            Column("claim_json", Text, nullable=False),
            Column("decision_json", Text, nullable=True),
            Column("workflow_json", Text, nullable=True),
            Column("decision_hash", String(200), nullable=True),
            Column("created_at", DateTime(timezone=True), nullable=False),
            PrimaryKeyConstraint("claim_id", "version"),
        )
        self._decisions = Table(
            "expense_claim_decisions",
            self._metadata,
            Column("claim_id", String(128), nullable=False),
            Column("version", Integer, nullable=False),
            Column("decision_json", Text, nullable=False),
            Column("workflow_json", Text, nullable=False),
            Column("decision_hash", String(200), nullable=True),
            Column("created_at", DateTime(timezone=True), nullable=False),
            PrimaryKeyConstraint("claim_id", "version"),
        )
        self._reviews = Table(
            "expense_claim_reviews",
            self._metadata,
            Column("approval_id", String(128), primary_key=True),
            Column("claim_id", String(128), nullable=False),
            Column("claim_version", Integer, nullable=False),
            Column("approval_status", String(32), nullable=False),
            Column("claim_status", String(32), nullable=False),
            Column("decision_json", Text, nullable=False),
            Column("resolution_json", Text, nullable=True),
            Column("decision_hash", String(200), nullable=True),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
        )
        self._events = Table(
            "expense_claim_events",
            self._metadata,
            Column("event_id", String(128), primary_key=True),
            Column("claim_id", String(128), nullable=False),
            Column("claim_version", Integer, nullable=False),
            Column("event_type", String(80), nullable=False),
            Column("actor_type", String(32), nullable=False),
            Column("actor_id", String(200), nullable=False),
            Column("request_id", String(200), nullable=False),
            Column("idempotency_key", String(300), nullable=False),
            Column("metadata_json", Text, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
        )
        self._idempotency = Table(
            "expense_claim_idempotency",
            self._metadata,
            Column("scope", String(40), nullable=False),
            Column("idempotency_key", String(300), nullable=False),
            Column("fingerprint", String(200), nullable=False),
            Column("result_json", Text, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            PrimaryKeyConstraint("scope", "idempotency_key"),
        )
        self._metadata.create_all(self._engine, checkfirst=True)

    @staticmethod
    def _dt(value: str | None = None) -> datetime:
        raw = value or _now()
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))

    @staticmethod
    def _claim_payload(row: Mapping[str, Any]) -> dict[str, Any]:
        value = json.loads(row["claim_json"])
        value["claim_id"] = row["claim_id"]
        value["version"] = row["current_version"]
        value["claim_version"] = row["current_version"]
        value["status"] = row["status"]
        value["applicant_id"] = row["applicant_id"]
        return value

    @staticmethod
    def _row_result(row: Mapping[str, Any], *, replay: bool = False, decision: Mapping[str, Any] | None = None, workflow: Mapping[str, Any] | None = None) -> dict[str, Any]:
        claim = ExpenseClaimStore._claim_payload(row)
        result = {"claim": claim, "claim_id": row["claim_id"], "version": row["current_version"], "status": row["status"], "idempotent_replay": replay}
        if decision:
            result["decision"] = dict(decision)
        if workflow:
            result["workflow"] = dict(workflow)
        return result

    @staticmethod
    def _review_result(row: Mapping[str, Any], *, events: list[dict[str, Any]], replay: bool = False) -> dict[str, Any]:
        result = {
            "claim_id": row["claim_id"],
            "claim_version": row["claim_version"],
            "status": row["claim_status"],
            "approval_id": row["approval_id"],
            "approval_status": row["approval_status"],
            "decision": json.loads(row["decision_json"]),
            "events": events,
            "idempotent_replay": replay,
        }
        if row.get("resolution_json"):
            result["resolution"] = json.loads(row["resolution_json"])
        return result

    def _event_rows(self, connection, claim_id: str, *, approval_id: str | None = None) -> list[dict[str, Any]]:
        statement = select(self._events).where(self._events.c.claim_id == claim_id).order_by(self._events.c.created_at, self._events.c.event_id)
        rows = connection.execute(statement).mappings().all()
        events = []
        for item in rows:
            metadata = json.loads(item["metadata_json"])
            if approval_id and metadata.get("approval_id") != approval_id and item["event_type"] in {"review_routed", "review_resolved"}:
                continue
            events.append({
                "event_id": item["event_id"], "claim_id": item["claim_id"],
                "claim_version": item["claim_version"], "event_type": item["event_type"],
                "actor_type": item["actor_type"], "actor_id": item["actor_id"],
                "request_id": item["request_id"], "idempotency_key": item["idempotency_key"],
                "created_at": item["created_at"].isoformat().replace("+00:00", "Z"),
                "metadata": metadata,
            })
        return events

    @staticmethod
    def _bind_decision(decision: Mapping[str, Any], *, claim_id: str, claim_version: int) -> dict[str, Any]:
        data = dict(decision)
        data.setdefault("claim_id", claim_id)
        data.setdefault("claim_version", claim_version)
        data.setdefault("policy_version", "expense-policy-sim-v1")
        data.setdefault("reasons", ["manual_review"])
        data.setdefault("decision_source", "rules")
        data.setdefault("decision_model", "expense-rules-v1")
        data.setdefault("rule_result", "not_covered")
        code = str(data.get("decision") or "")
        if data.get("handoff") is None and (
            data.get("review_required")
            or code in {"approve_manager", "approve_finance", "approve_director", "needs_review", "escalated"}
        ):
            data["handoff"] = Handoff(
                reason_code=str((data.get("reasons") or ["manual_review"])[0]),
                risk_level="medium",
                amount_band="0-1000",
            ).to_dict()
        return Decision.from_dict(data).to_dict()

    def _get_claim_row(self, connection, claim_id: str, *, lock: bool = False):
        statement = select(self._claims).where(self._claims.c.claim_id == claim_id)
        if lock and self._engine.dialect.name == "postgresql":
            statement = statement.with_for_update()
        return connection.execute(statement).mappings().first()

    def _check_access(self, row: Mapping[str, Any] | None, actor_id: str):
        if row is None:
            raise ExpenseStoreError("claim_not_found", "expense claim not found", status_code=404)
        if row["applicant_id"] != actor_id:
            raise ExpenseStoreError("forbidden_claim_access", "expense claim not found", status_code=404)

    def _idem(self, connection, scope: str, key: str, payload: Any) -> dict[str, Any] | None:
        if not key:
            return None
        row = connection.execute(
            select(self._idempotency).where(
                self._idempotency.c.scope == scope,
                self._idempotency.c.idempotency_key == key,
            )
        ).mappings().first()
        if row is None:
            return None
        if row["fingerprint"] != _fingerprint(payload):
            raise ExpenseStoreError("idempotency_conflict", "idempotency key conflicts with an existing request")
        result = json.loads(row["result_json"])
        result["idempotent_replay"] = True
        return result

    def _save_idem(self, connection, scope: str, key: str, payload: Any, result: Mapping[str, Any]) -> None:
        if not key:
            return
        connection.execute(self._idempotency.insert().values(
            scope=scope,
            idempotency_key=key,
            fingerprint=_fingerprint(payload),
            result_json=_json(result),
            created_at=self._dt(),
        ))

    def replay(self, scope: str, key: str, payload: Any) -> dict[str, Any] | None:
        """Return a stored idempotent result before running business logic."""
        if not key:
            return None
        with self._engine.connect() as connection:
            return self._idem(connection, scope, key, payload)

    def _event(self, connection, *, claim_id: str, version: int, event_type: str, actor_type: str, actor_id: str, request_id: str, idempotency_key: str, metadata: Mapping[str, Any]) -> dict[str, Any]:
        created_at = self._dt()
        previous = connection.execute(
            select(self._events.c.created_at)
            .where(self._events.c.claim_id == claim_id)
            .order_by(self._events.c.created_at.desc(), self._events.c.event_id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if previous is not None and previous.tzinfo is None:
            previous = previous.replace(tzinfo=timezone.utc)
        if previous is not None and created_at <= previous:
            created_at = previous + timedelta(microseconds=1)
        event = {
            "event_id": "evt_" + uuid.uuid4().hex,
            "claim_id": claim_id,
            "claim_version": version,
            "event_type": event_type,
            "actor_type": actor_type,
            "actor_id": actor_id,
            "request_id": request_id or "expense-s4",
            "idempotency_key": idempotency_key or "expense-s4",
            "created_at": created_at,
            "metadata": dict(metadata),
        }
        connection.execute(self._events.insert().values(
            event_id=event["event_id"],
            claim_id=claim_id,
            claim_version=version,
            event_type=event_type,
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=event["request_id"],
            idempotency_key=event["idempotency_key"],
            metadata_json=_json(metadata),
            created_at=event["created_at"],
        ))
        event["created_at"] = event["created_at"].isoformat().replace("+00:00", "Z")
        return event

    def create(self, payload: Mapping[str, Any], *, actor_id: str, request_id: str, idempotency_key: str) -> dict[str, Any]:
        requested_claim_id = payload.get("claim_id")
        claim_id = str(requested_claim_id or ("clm_" + uuid.uuid4().hex))
        body = copy.deepcopy(dict(payload))
        body.pop("claim_id", None)
        body.pop("applicant_id", None)
        body.pop("version", None)
        body.pop("claim_version", None)
        body["claim_id"] = claim_id
        body["version"] = 1
        body["claim_version"] = 1
        body["status"] = "draft"
        body["applicant_id"] = actor_id
        fingerprint_payload = {
            "actor_id": actor_id,
            "claim_id": str(requested_claim_id) if requested_claim_id else None,
            "payload": {key: value for key, value in body.items() if key not in {"claim_id", "version", "claim_version", "status", "applicant_id"}},
        }
        with self._engine.begin() as connection:
            replay = self._idem(connection, "create", idempotency_key, fingerprint_payload)
            if replay is not None:
                return replay
            if self._get_claim_row(connection, claim_id) is not None:
                raise ExpenseStoreError("idempotency_conflict", "claim_id already exists")
            now = self._dt()
            connection.execute(self._claims.insert().values(
                claim_id=claim_id, applicant_id=actor_id, current_version=1, status="draft",
                claim_json=_json(body), created_at=now, updated_at=now,
            ))
            connection.execute(self._versions.insert().values(
                claim_id=claim_id, version=1, status="draft", claim_json=_json(body),
                created_at=now,
            ))
            self._event(connection, claim_id=claim_id, version=1, event_type="claim_created", actor_type="applicant", actor_id=actor_id, request_id=request_id, idempotency_key=idempotency_key, metadata={})
            result = {"claim": body, "claim_id": claim_id, "version": 1, "status": "draft", "idempotent_replay": False}
            self._save_idem(connection, "create", idempotency_key, fingerprint_payload, result)
            return result

    def get(self, claim_id: str, *, actor_id: str) -> dict[str, Any]:
        with self._engine.connect() as connection:
            row = self._get_claim_row(connection, claim_id)
            decision_row = None
            review_row = None
            if row is not None:
                decision_row = connection.execute(
                    select(self._decisions).where(
                        self._decisions.c.claim_id == claim_id,
                        self._decisions.c.version == row["current_version"],
                    )
                ).mappings().first()
                review_row = connection.execute(
                    select(self._reviews).where(
                        self._reviews.c.claim_id == claim_id,
                        self._reviews.c.claim_version == row["current_version"],
                    )
                ).mappings().first()
        self._check_access(row, actor_id)
        result = self._row_result(
            row,
            decision=json.loads(decision_row["decision_json"]) if decision_row else None,
            workflow=json.loads(decision_row["workflow_json"]) if decision_row else None,
        )
        if review_row is not None:
            result["review"] = self._review_result(review_row, events=[])
            result["approval_id"] = review_row["approval_id"]
            result["approval_status"] = review_row["approval_status"]
        return result

    def update(self, claim_id: str, patch: Mapping[str, Any], *, actor_id: str, expected_version: int, request_id: str, idempotency_key: str) -> dict[str, Any]:
        fingerprint_payload = {"claim_id": claim_id, "actor_id": actor_id, "expected_version": expected_version, "patch": dict(patch)}
        with self._engine.begin() as connection:
            replay = self._idem(connection, "update", idempotency_key, fingerprint_payload)
            if replay is not None:
                return replay
            row = self._get_claim_row(connection, claim_id, lock=True)
            self._check_access(row, actor_id)
            if row["current_version"] != expected_version:
                raise ExpenseStoreError("claim_version_mismatch", "claim version does not match expected_version")
            if row["status"] not in {"draft", "needs_correction"}:
                raise ExpenseStoreError("claim_not_editable", "claim is not editable")
            body = json.loads(row["claim_json"])
            for key, value in dict(patch).items():
                if key not in {"claim_id", "applicant_id", "version", "claim_version", "status"}:
                    body[key] = copy.deepcopy(value)
            new_version = expected_version + 1
            body.update(claim_id=claim_id, version=new_version, claim_version=new_version, applicant_id=actor_id, status="draft")
            now = self._dt()
            connection.execute(update(self._claims).where(self._claims.c.claim_id == claim_id, self._claims.c.current_version == expected_version).values(current_version=new_version, status="draft", claim_json=_json(body), updated_at=now))
            connection.execute(self._versions.insert().values(claim_id=claim_id, version=new_version, status="draft", claim_json=_json(body), created_at=now))
            self._event(connection, claim_id=claim_id, version=new_version, event_type="claim_updated", actor_type="applicant", actor_id=actor_id, request_id=request_id, idempotency_key=idempotency_key, metadata={"previous_version": expected_version})
            result = {"claim": body, "claim_id": claim_id, "version": new_version, "status": "draft", "idempotent_replay": False}
            self._save_idem(connection, "update", idempotency_key, fingerprint_payload, result)
            return result

    def _route_review_in_transaction(
        self,
        connection,
        *,
        claim_id: str,
        claim_version: int,
        decision: Mapping[str, Any],
        request_id: str,
        idempotency_key: str,
        workflow: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        decision = self._bind_decision(decision, claim_id=claim_id, claim_version=claim_version)
        code = str(decision["decision"])
        hard_rejections = {
            "reject_no_receipt", "reject_over_limit", "reject_missing_purchase_order", "reject_policy",
        }
        needs_review = bool(decision.get("review_required")) or code in {
            "approve_manager", "approve_finance", "approve_director", "needs_review", "escalated",
        }
        if code in hard_rejections:
            status = "rejected"
            event = self._event(
                connection, claim_id=claim_id, version=claim_version,
                event_type="claim_rejected", actor_type="agent", actor_id="expense-router",
                request_id=request_id, idempotency_key=idempotency_key,
                metadata={"decision_hash": decision.get("decision_hash"), "decision_code": code},
            )
            return {
                "claim_id": claim_id, "claim_version": claim_version, "status": status,
                "approval_id": None, "decision": dict(decision), "events": [event],
            }
        if not needs_review:
            event = self._event(
                connection, claim_id=claim_id, version=claim_version,
                event_type="decision_routed", actor_type="agent", actor_id="expense-router",
                request_id=request_id, idempotency_key=idempotency_key,
                metadata={"decision_hash": decision.get("decision_hash")},
            )
            return {
                "claim_id": claim_id, "claim_version": claim_version, "status": "submitted",
                "approval_id": None, "decision": dict(decision), "events": [event],
            }

        existing = connection.execute(
            select(self._reviews).where(
                self._reviews.c.claim_id == claim_id,
                self._reviews.c.claim_version == claim_version,
            )
        ).mappings().first()
        if existing is not None:
            if existing["decision_json"] != _json(dict(decision)):
                raise ExpenseStoreError("review_conflict", "claim version already has a different review")
            return self._review_result(
                existing,
                events=self._event_rows(connection, claim_id, approval_id=existing["approval_id"]),
                replay=True,
            )

        approval_id = "apr_" + uuid.uuid4().hex
        status = "escalated" if code == "escalated" else "under_review"
        now = self._dt()
        connection.execute(self._reviews.insert().values(
            approval_id=approval_id,
            claim_id=claim_id,
            claim_version=claim_version,
            approval_status="pending",
            claim_status=status,
            decision_json=_json(dict(decision)),
            resolution_json=None,
            decision_hash=decision.get("decision_hash"),
            created_at=now,
            updated_at=now,
        ))
        event = self._event(
            connection, claim_id=claim_id, version=claim_version,
            event_type="review_routed", actor_type="agent", actor_id="expense-router",
            request_id=request_id, idempotency_key=idempotency_key,
            metadata={
                "approval_id": approval_id,
                "decision_hash": decision.get("decision_hash"),
                "handoff": decision.get("handoff"),
            },
        )
        row = connection.execute(
            select(self._reviews).where(self._reviews.c.approval_id == approval_id)
        ).mappings().one()
        result = self._review_result(row, events=[event])
        if workflow is not None:
            result["workflow"] = dict(workflow)
        return result

    def route_review(
        self,
        claim_id: str,
        *,
        claim_version: int,
        decision: Mapping[str, Any],
        request_id: str = "",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        payload = {
            "claim_id": claim_id, "claim_version": claim_version,
            "decision": dict(decision),
        }
        with self._engine.begin() as connection:
            replay = self._idem(connection, "route_review", idempotency_key, payload)
            if replay is not None:
                return replay
            row = self._get_claim_row(connection, claim_id, lock=True)
            if row is None:
                raise ExpenseStoreError("claim_not_found", "expense claim not found", status_code=404)
            if row["current_version"] != claim_version:
                raise ExpenseStoreError("claim_version_mismatch", "claim version does not match review")
            result = self._route_review_in_transaction(
                connection, claim_id=claim_id, claim_version=claim_version,
                decision=decision, request_id=request_id,
                idempotency_key=idempotency_key or "expense-review", workflow=None,
            )
            body = json.loads(row["claim_json"])
            body["status"] = result["status"]
            connection.execute(update(self._claims).where(self._claims.c.claim_id == claim_id).values(status=result["status"], claim_json=_json(body), updated_at=self._dt()))
            result["idempotent_replay"] = False
            self._save_idem(connection, "route_review", idempotency_key, payload, result)
            return result

    def resolve_review(
        self,
        approval_id: str,
        *,
        decision: str,
        approver_id: str,
        claim_id: str,
        expected_version: int,
        decision_hash: str,
        request_id: str = "",
        idempotency_key: str = "",
        comment: str = "",
    ) -> dict[str, Any]:
        with self._engine.begin() as connection:
            if self._engine.dialect.name == "sqlite":
                # Match H3's write transaction; a deferred SELECT can otherwise
                # observe pending before another resolver commits its decision.
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            return self._resolve_review_in_transaction(connection, approval_id, decision=decision,
                approver_id=approver_id, claim_id=claim_id, expected_version=expected_version,
                decision_hash=decision_hash, request_id=request_id,
                idempotency_key=idempotency_key, comment=comment)

    def _pending_review(self, connection, approval_id, *, claim_id, expected_version, decision_hash):
        # A single lock order for direct S5 and H3: Claim -> [case] -> review.
        claim = self._get_claim_row(connection, claim_id, lock=True)
        if claim is None:
            raise ExpenseStoreError("claim_not_found", "expense claim not found", status_code=404)
        if claim["current_version"] != expected_version:
            raise ExpenseStoreError("approval_version_mismatch", "claim version changed before resolution")
        review = connection.execute(
            select(self._reviews).where(self._reviews.c.approval_id == approval_id).with_for_update()
            if self._engine.dialect.name == "postgresql" else
            select(self._reviews).where(self._reviews.c.approval_id == approval_id)
        ).mappings().first()
        if review is None:
            raise ExpenseStoreError("claim_not_found", "expense approval not found", status_code=404)
        if review["claim_id"] != claim_id:
            raise ExpenseStoreError("forbidden_claim_access", "approval is not bound to this claim", status_code=403)
        if review["claim_version"] != expected_version:
            raise ExpenseStoreError("approval_version_mismatch", "approval claim version does not match")
        if review["decision_hash"] != decision_hash:
            raise ExpenseStoreError("decision_invalid", "decision_hash does not match the routed decision")
        if review["approval_status"] != "pending":
            raise ExpenseStoreError("approval_not_pending", "expense approval has already been resolved")
        return review, claim

    def _resolve_review_in_transaction(
        self, connection,
        approval_id: str,
        *,
        decision: str,
        approver_id: str,
        claim_id: str,
        expected_version: int,
        decision_hash: str,
        request_id: str = "",
        idempotency_key: str = "",
        comment: str = "",
    ) -> dict[str, Any]:
        payload = {
            "approval_id": approval_id, "claim_id": claim_id,
            "expected_version": expected_version, "decision_hash": decision_hash,
            "decision": decision, "approver_id": approver_id, "comment": comment,
        }
        replay = self._idem(connection, "resolve_review", idempotency_key, payload)
        if replay is not None:
            return replay
        review, claim = self._pending_review(connection, approval_id, claim_id=claim_id,
            expected_version=expected_version, decision_hash=decision_hash)
        if decision not in {"approve", "reject", "escalate"}:
            raise ExpenseStoreError("invalid_decision", "decision must be approve, reject, or escalate")
        status = {"approve": "approved", "reject": "rejected", "escalate": "escalated"}[decision]
        resolution = {
            "approval_id": approval_id, "claim_id": claim_id,
            "claim_version": expected_version, "decision_hash": decision_hash,
            "decision": decision, "approver_id": approver_id,
            "comment": comment, "created_at": _now(),
        }
        now = self._dt()
        connection.execute(update(self._reviews).where(self._reviews.c.approval_id == approval_id).values(
            approval_status="resolved", claim_status=status,
            resolution_json=_json(resolution), updated_at=now,
        ))
        body = json.loads(claim["claim_json"])
        body["status"] = status
        connection.execute(update(self._claims).where(self._claims.c.claim_id == claim_id).values(status=status, claim_json=_json(body), updated_at=now))
        self._event(
            connection, claim_id=claim_id, version=expected_version,
            event_type="review_resolved", actor_type="manager", actor_id=approver_id,
            request_id=request_id, idempotency_key=idempotency_key or "expense-review",
            metadata={"approval_id": approval_id, "decision": decision, "decision_hash": decision_hash, "comment": comment},
        )
        row = connection.execute(select(self._reviews).where(self._reviews.c.approval_id == approval_id)).mappings().one()
        result = self._review_result(row, events=self._event_rows(connection, claim_id, approval_id=approval_id))
        self._save_idem(connection, "resolve_review", idempotency_key, payload, result)
        return result

    def submit(self, claim_id: str, *, actor_id: str, expected_version: int, request_id: str, idempotency_key: str, workflow_runner: Callable[[Mapping[str, Any]], Mapping[str, Any]]) -> dict[str, Any]:
        fingerprint_payload = {"claim_id": claim_id, "actor_id": actor_id, "expected_version": expected_version}
        with self._engine.begin() as connection:
            replay = self._idem(connection, "submit", idempotency_key, fingerprint_payload)
            if replay is not None:
                return replay
            row = self._get_claim_row(connection, claim_id, lock=True)
            self._check_access(row, actor_id)
            if row["current_version"] != expected_version:
                raise ExpenseStoreError("claim_version_mismatch", "claim version does not match expected_version")
            if row["status"] not in {"draft", "needs_correction"}:
                raise ExpenseStoreError("invalid_state_transition", "claim cannot be submitted from its current state")
            workflow_result = dict(workflow_runner(copy.deepcopy(json.loads(row["claim_json"]))))
            state = dict(workflow_result.get("state") or {})
            decision = self._bind_decision(
                dict(state.get("decision") or {}),
                claim_id=claim_id,
                claim_version=expected_version,
            )
            state["decision"] = decision
            workflow_result["state"] = state
            code = str(state.get("decision_code") or decision.get("decision") or "")
            if not state.get("claim_valid", True):
                status = "needs_correction"
            elif code.startswith("reject_"):
                status = "rejected"
            elif code == "escalated":
                status = "escalated"
            elif state.get("decision", {}).get("review_required") or code == "needs_review" or code.startswith("approve_"):
                status = "under_review"
            else:
                status = "submitted"
            body = json.loads(row["claim_json"])
            body.update(claim_id=claim_id, version=expected_version, claim_version=expected_version, applicant_id=actor_id, status=status)
            now = self._dt()
            decision_hash = decision.get("decision_hash")
            connection.execute(
                update(self._claims)
                .where(
                    self._claims.c.claim_id == claim_id,
                    self._claims.c.current_version == expected_version,
                )
                .values(status=status, claim_json=_json(body), updated_at=now)
            )
            connection.execute(
                self._decisions.insert().values(
                    claim_id=claim_id,
                    version=expected_version,
                    decision_json=_json(decision),
                    workflow_json=_json(workflow_result),
                    decision_hash=decision_hash,
                    created_at=now,
                )
            )
            self._event(connection, claim_id=claim_id, version=expected_version, event_type="claim_submitted", actor_type="applicant", actor_id=actor_id, request_id=request_id, idempotency_key=idempotency_key, metadata={"decision_code": code, "decision_hash": decision_hash, "workflow_run_id": workflow_result.get("run_id")})
            result = {"claim": body, "claim_id": claim_id, "version": expected_version, "status": status, "decision": decision, "decision_code": code, "workflow": dict(workflow_result), "idempotent_replay": False}
            if status != "needs_correction":
                review_result = self._route_review_in_transaction(
                    connection,
                    claim_id=claim_id,
                    claim_version=expected_version,
                    decision=decision,
                    request_id=request_id,
                    idempotency_key=f"{idempotency_key}:route",
                    workflow=workflow_result,
                )
                result["review"] = review_result
                result["approval_id"] = review_result.get("approval_id")
                result["approval_status"] = review_result.get("approval_status")
            self._save_idem(connection, "submit", idempotency_key, fingerprint_payload, result)
            return result

    def events(self, claim_id: str, *, actor_id: str) -> list[dict[str, Any]]:
        with self._engine.connect() as connection:
            row = self._get_claim_row(connection, claim_id)
            self._check_access(row, actor_id)
            rows = connection.execute(select(self._events).where(self._events.c.claim_id == claim_id).order_by(self._events.c.created_at, self._events.c.event_id)).mappings().all()
        return [{"event_id": item["event_id"], "claim_id": item["claim_id"], "claim_version": item["claim_version"], "event_type": item["event_type"], "actor_type": item["actor_type"], "actor_id": item["actor_id"], "request_id": item["request_id"], "idempotency_key": item["idempotency_key"], "created_at": item["created_at"].isoformat().replace("+00:00", "Z"), "metadata": json.loads(item["metadata_json"])} for item in rows]

    def list_reviews(self, *, claim_id: str | None = None) -> list[dict[str, Any]]:
        with self._engine.connect() as connection:
            statement = select(self._reviews).order_by(self._reviews.c.created_at, self._reviews.c.approval_id)
            if claim_id:
                statement = statement.where(self._reviews.c.claim_id == claim_id)
            rows = connection.execute(statement).mappings().all()
            return [self._review_result(row, events=self._event_rows(connection, row["claim_id"], approval_id=row["approval_id"])) for row in rows]

    def close(self) -> None:
        self._engine.dispose()


__all__ = ["ExpenseClaimStore", "ExpenseStoreError"]
