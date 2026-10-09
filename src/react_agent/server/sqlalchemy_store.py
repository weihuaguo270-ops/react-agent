"""SQLAlchemy-backed task persistence.

The service uses PostgreSQL in deployment through the ``postgresql+psycopg``
URL. SQLite is also accepted by the store so the persistence contract can be
tested without requiring a database server.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    or_,
    and_,
    select,
    update,
)
from sqlalchemy.engine import Engine
from sqlalchemy.dialects.postgresql import insert as pg_insert

if TYPE_CHECKING:
    from react_agent.server.task_manager import TaskRecord


class SQLAlchemyTaskStore:
    """Persist task records in a SQLAlchemy-supported relational database."""

    def __init__(self, url: str | None = None, *, engine: Engine | None = None):
        resolved_url = (
            url
            or os.environ.get("REACT_AGENT_DATABASE_URL")
            or os.environ.get("REACT_AGENT_POSTGRES_URL")
        )
        if engine is None and not resolved_url:
            raise ValueError(
                "REACT_AGENT_DATABASE_URL or REACT_AGENT_POSTGRES_URL is required"
            )
        self._engine = engine or create_engine(
            resolved_url,
            pool_pre_ping=True,
        )
        if self._engine.dialect.name not in {"postgresql", "sqlite"}:
            raise ValueError("task storage requires a PostgreSQL or SQLite URL")
        self._metadata = MetaData()
        self._tasks = Table(
            "react_agent_tasks",
            self._metadata,
            # Keep the schema compatible with the previous task store.
            Column("task_id", String(64), primary_key=True),
            Column("status", String(32), nullable=False),
            Column("created_at", Float, nullable=False),
            Column("started_at", Float, nullable=True),
            Column("finished_at", Float, nullable=True),
            Column("result_json", Text, nullable=True),
            Column("error_text", String(1000), nullable=True),
            Column("updated_at", DateTime(timezone=True), nullable=True),
        )
        self._metadata.create_all(self._engine, checkfirst=True)

    def save(self, record: TaskRecord) -> None:
        values = {
            "task_id": record.task_id,
            "status": record.status,
            "created_at": record.created_at,
            "started_at": record.started_at,
            "finished_at": record.finished_at,
            "result_json": (
                json.dumps(record.result, ensure_ascii=False)
                if record.result is not None
                else None
            ),
            "error_text": record.error,
            "updated_at": datetime.now(timezone.utc),
        }
        allowed_previous = {
            "queued": {"queued"},
            "running": {"queued", "running", "retry_wait"},
            "succeeded": {"queued", "running", "retry_wait"},
            "failed": {"queued", "running", "retry_wait"},
            "cancelled": {"queued", "running", "retry_wait"},
        }.get(record.status, {record.status})
        with self._engine.begin() as connection:
            if self._engine.dialect.name == "postgresql":
                statement = pg_insert(self._tasks).values(**values)
                statement = statement.on_conflict_do_update(
                    index_elements=[self._tasks.c.task_id],
                    set_={key: statement.excluded[key] for key in values if key != "task_id"},
                    where=self._tasks.c.status.in_(allowed_previous),
                )
                connection.execute(statement)
            else:
                # SQLite is used by the local persistence tests.
                from sqlalchemy.dialects.sqlite import insert as sqlite_insert

                statement = sqlite_insert(self._tasks).values(**values)
                statement = statement.on_conflict_do_update(
                    index_elements=[self._tasks.c.task_id],
                    set_={key: statement.excluded[key] for key in values if key != "task_id"},
                    where=self._tasks.c.status.in_(allowed_previous),
                )
                connection.execute(statement)

    def claim(self, task_id: str, *, now: float, visibility_seconds: float) -> TaskRecord | None:
        """Claim queued or expired work atomically; started_at fences each attempt."""
        with self._engine.begin() as connection:
            row = connection.execute(
                update(self._tasks).where(
                    self._tasks.c.task_id == task_id,
                    or_(
                        self._tasks.c.status == "queued",
                        and_(
                            self._tasks.c.status == "running",
                            self._tasks.c.started_at <= now - visibility_seconds,
                        ),
                    ),
                ).values(status="running", started_at=now, updated_at=datetime.now(timezone.utc))
                .returning(self._tasks)
            ).mappings().first()
        return self._record(row) if row is not None else None

    def finish(self, record: TaskRecord) -> bool:
        """Only the current running attempt may commit a terminal result."""
        with self._engine.begin() as connection:
            changed = connection.execute(
                update(self._tasks).where(
                    self._tasks.c.task_id == record.task_id,
                    self._tasks.c.status == "running",
                    self._tasks.c.started_at == record.started_at,
                ).values(
                    status=record.status, finished_at=record.finished_at,
                    result_json=json.dumps(record.result, ensure_ascii=False) if record.result is not None else None,
                    error_text=record.error[:500] if record.error else None,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            return changed.rowcount == 1

    def cancel(self, task_id: str) -> TaskRecord | None:
        import time

        with self._engine.begin() as connection:
            connection.execute(update(self._tasks).where(
                self._tasks.c.task_id == task_id,
                self._tasks.c.status.in_({"queued", "running"}),
            ).values(status="cancelled", finished_at=time.time(), updated_at=datetime.now(timezone.utc)))
        return self.get(task_id)

    @staticmethod
    def _record(row) -> TaskRecord:
        from react_agent.server.task_manager import TaskRecord

        return TaskRecord(
            task_id=row["task_id"], status=row["status"], created_at=row["created_at"],
            started_at=row["started_at"], finished_at=row["finished_at"],
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            error=row["error_text"],
        )

    def get(self, task_id: str) -> TaskRecord | None:
        from react_agent.server.task_manager import TaskRecord

        with self._engine.connect() as connection:
            row = connection.execute(
                select(self._tasks).where(self._tasks.c.task_id == task_id)
            ).mappings().first()
        if row is None:
            return None
        return self._record(row)

    def close(self) -> None:
        self._engine.dispose()


# Explicit name for the production backend; retain the generic name for
# callers that already selected the SQLAlchemy backend before PostgreSQL was
# wired in.
PostgreSQLTaskStore = SQLAlchemyTaskStore
