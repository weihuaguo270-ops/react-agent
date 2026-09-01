"""SQLAlchemy persistence for versioned security triage cases."""
from __future__ import annotations

import json
import os
import time
import uuid
from copy import deepcopy
from typing import Any

from sqlalchemy import Float, ForeignKey, Integer, String, Text, create_engine, select, update
from sqlalchemy.orm import mapped_column, sessionmaker

from react_agent.server.sqlalchemy_store import Base

from .models import ReviewInput
from .report import render_report


class SecurityCaseRow(Base):
    __tablename__ = "security_triage_cases"

    case_id = mapped_column(String(64), primary_key=True)
    version = mapped_column(Integer, nullable=False)
    status = mapped_column(String(32), nullable=False)
    created_at = mapped_column(Float, nullable=False)
    updated_at = mapped_column(Float, nullable=False)
    request_json = mapped_column(Text, nullable=False)
    case_json = mapped_column(Text, nullable=False)
    answer_text = mapped_column(Text, nullable=False)


class SecurityReviewRow(Base):
    __tablename__ = "security_triage_review_events"

    review_id = mapped_column(String(64), primary_key=True)
    case_id = mapped_column(
        String(64), ForeignKey("security_triage_cases.case_id", ondelete="CASCADE"), nullable=False, index=True
    )
    case_version = mapped_column(Integer, nullable=False)
    decision = mapped_column(String(32), nullable=False)
    reviewer = mapped_column(String(200), nullable=False)
    notes = mapped_column(Text, nullable=False)
    created_at = mapped_column(Float, nullable=False)


class SecurityCaseNotFound(KeyError):
    pass


class SecurityCaseConflict(RuntimeError):
    pass


class SecurityCaseStore:
    """Persist immutable evidence snapshots and optimistic-lock review decisions."""

    def __init__(self, url: str | None = None, *, create_schema: bool = True):
        self.url = (
            url
            or os.environ.get("REACT_AGENT_SECURITY_DATABASE_URL")
            or os.environ.get("REACT_AGENT_DATABASE_URL")
            or "sqlite:///react_agent_security.db"
        )
        connect_args = {"check_same_thread": False} if self.url.startswith("sqlite") else {}
        self.engine = create_engine(self.url, pool_pre_ping=True, connect_args=connect_args)
        self._session = sessionmaker(self.engine, expire_on_commit=False)
        if create_schema:
            Base.metadata.create_all(self.engine)

    @staticmethod
    def _public(row: SecurityCaseRow) -> dict[str, Any]:
        return {
            "case_id": row.case_id,
            "version": row.version,
            "status": row.status,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "request": json.loads(row.request_json),
            "case": json.loads(row.case_json),
            "answer": row.answer_text,
        }

    def create(self, request: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        case_id = uuid.uuid4().hex
        case = deepcopy(result["case"])
        case.update(
            {
                "case_id": case_id,
                "version": 1,
                "status": "pending_review",
                "created_at": now,
                "updated_at": now,
            }
        )
        case["review"] = {
            "required": True,
            "decision": "pending_review",
            "reviewer": None,
            "notes": "",
        }
        answer = render_report(case)
        row = SecurityCaseRow(
            case_id=case_id,
            version=1,
            status="pending_review",
            created_at=now,
            updated_at=now,
            request_json=json.dumps(request, ensure_ascii=False),
            case_json=json.dumps(case, ensure_ascii=False),
            answer_text=answer,
        )
        with self._session.begin() as session:
            session.add(row)
        return self._public(row)

    def get(self, case_id: str) -> dict[str, Any] | None:
        with self._session() as session:
            row = session.get(SecurityCaseRow, case_id)
            return self._public(row) if row is not None else None

    def review(
        self,
        case_id: str,
        *,
        expected_version: int,
        review: dict[str, Any],
    ) -> dict[str, Any]:
        if expected_version < 1:
            raise ValueError("expected_version must be at least 1")
        decision = ReviewInput.from_value(review)
        if decision is None:
            raise ValueError("review is required")
        now = time.time()
        with self._session.begin() as session:
            current = session.get(SecurityCaseRow, case_id)
            if current is None:
                raise SecurityCaseNotFound(case_id)
            if current.version != expected_version or current.status != "pending_review":
                raise SecurityCaseConflict(
                    f"case version/status changed: expected pending_review v{expected_version}, "
                    f"found {current.status} v{current.version}"
                )
            next_version = current.version + 1
            case = json.loads(current.case_json)
            case["status"] = decision.decision
            case["version"] = next_version
            case["updated_at"] = now
            case["review"] = {
                "required": True,
                "decision": decision.decision,
                "reviewer": decision.reviewer,
                "notes": decision.notes,
            }
            answer = render_report(case)
            changed = session.execute(
                update(SecurityCaseRow)
                .where(
                    SecurityCaseRow.case_id == case_id,
                    SecurityCaseRow.version == expected_version,
                    SecurityCaseRow.status == "pending_review",
                )
                .values(
                    version=next_version,
                    status=decision.decision,
                    updated_at=now,
                    case_json=json.dumps(case, ensure_ascii=False),
                    answer_text=answer,
                )
            )
            if changed.rowcount != 1:
                raise SecurityCaseConflict("case was reviewed concurrently")
            session.add(
                SecurityReviewRow(
                    review_id=uuid.uuid4().hex,
                    case_id=case_id,
                    case_version=next_version,
                    decision=decision.decision,
                    reviewer=decision.reviewer,
                    notes=decision.notes,
                    created_at=now,
                )
            )
        result = self.get(case_id)
        if result is None:  # pragma: no cover - committed row cannot disappear normally
            raise SecurityCaseNotFound(case_id)
        return result

    def list_reviews(self, case_id: str) -> list[dict[str, Any]]:
        if self.get(case_id) is None:
            raise SecurityCaseNotFound(case_id)
        with self._session() as session:
            rows = session.scalars(
                select(SecurityReviewRow)
                .where(SecurityReviewRow.case_id == case_id)
                .order_by(SecurityReviewRow.created_at, SecurityReviewRow.review_id)
            ).all()
            return [
                {
                    "review_id": row.review_id,
                    "case_id": row.case_id,
                    "case_version": row.case_version,
                    "decision": row.decision,
                    "reviewer": row.reviewer,
                    "notes": row.notes,
                    "created_at": row.created_at,
                }
                for row in rows
            ]

    def close(self) -> None:
        self.engine.dispose()
