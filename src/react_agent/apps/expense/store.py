"""SQLAlchemy-backed persistence for the formal Expense Claim lifecycle."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
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

    def _event(self, connection, *, claim_id: str, version: int, event_type: str, actor_type: str, actor_id: str, request_id: str, idempotency_key: str, metadata: Mapping[str, Any]) -> None:
        connection.execute(self._events.insert().values(
            event_id="evt_" + uuid.uuid4().hex,
            claim_id=claim_id,
            claim_version=version,
            event_type=event_type,
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=request_id or "expense-s4",
            idempotency_key=idempotency_key or "expense-s4",
            metadata_json=_json(metadata),
            created_at=self._dt(),
        ))

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
            if row is not None:
                decision_row = connection.execute(
                    select(self._decisions).where(
                        self._decisions.c.claim_id == claim_id,
                        self._decisions.c.version == row["current_version"],
                    )
                ).mappings().first()
        self._check_access(row, actor_id)
        return self._row_result(
            row,
            decision=json.loads(decision_row["decision_json"]) if decision_row else None,
            workflow=json.loads(decision_row["workflow_json"]) if decision_row else None,
        )

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
            decision = dict(state.get("decision") or {})
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
            self._save_idem(connection, "submit", idempotency_key, fingerprint_payload, result)
            return result

    def events(self, claim_id: str, *, actor_id: str) -> list[dict[str, Any]]:
        with self._engine.connect() as connection:
            row = self._get_claim_row(connection, claim_id)
            self._check_access(row, actor_id)
            rows = connection.execute(select(self._events).where(self._events.c.claim_id == claim_id).order_by(self._events.c.created_at, self._events.c.event_id)).mappings().all()
        return [{"event_id": item["event_id"], "claim_id": item["claim_id"], "claim_version": item["claim_version"], "event_type": item["event_type"], "actor_type": item["actor_type"], "actor_id": item["actor_id"], "request_id": item["request_id"], "idempotency_key": item["idempotency_key"], "created_at": item["created_at"].isoformat().replace("+00:00", "Z"), "metadata": json.loads(item["metadata_json"])} for item in rows]

    def close(self) -> None:
        self._engine.dispose()


__all__ = ["ExpenseClaimStore", "ExpenseStoreError"]
