"""SQLAlchemy task persistence shared by SQLite and server databases."""
from __future__ import annotations

import json
import os

from sqlalchemy import Float, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, mapped_column, sessionmaker

from react_agent.server.task_manager import TaskRecord


class Base(DeclarativeBase):
    pass


class TaskRow(Base):
    __tablename__ = "react_agent_tasks"

    task_id = mapped_column(String(64), primary_key=True)
    status = mapped_column(String(32), nullable=False)
    created_at = mapped_column(Float, nullable=False)
    started_at = mapped_column(Float, nullable=True)
    finished_at = mapped_column(Float, nullable=True)
    result_json = mapped_column(Text, nullable=True)
    error_text = mapped_column(String(1000), nullable=True)


class SQLAlchemyTaskStore:
    """Persist task state through one SQLAlchemy 2.x model."""

    def __init__(self, url: str | None = None, *, create_schema: bool = True):
        self.url = url or os.environ.get("REACT_AGENT_DATABASE_URL")
        if not self.url:
            raise ValueError("REACT_AGENT_DATABASE_URL is required for sqlalchemy storage")
        connect_args = {"check_same_thread": False} if self.url.startswith("sqlite") else {}
        self.engine = create_engine(
            self.url,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
        self._session = sessionmaker(self.engine, expire_on_commit=False)
        if create_schema:
            # 本地与测试环境可自动建表；部署环境应先执行 Alembic migration。
            Base.metadata.create_all(self.engine)

    def save(self, record: TaskRecord) -> None:
        with self._session.begin() as session:
            row = session.get(TaskRow, record.task_id)
            if row is None:
                row = TaskRow(task_id=record.task_id)
                session.add(row)
            row.status = record.status
            row.created_at = record.created_at
            row.started_at = record.started_at
            row.finished_at = record.finished_at
            row.result_json = (
                json.dumps(record.result, ensure_ascii=False)
                if record.result is not None
                else None
            )
            row.error_text = record.error

    def get(self, task_id: str) -> TaskRecord | None:
        with self._session() as session:
            row = session.get(TaskRow, task_id)
            if row is None:
                return None
            return TaskRecord(
                task_id=row.task_id,
                status=row.status,
                created_at=row.created_at,
                started_at=row.started_at,
                finished_at=row.finished_at,
                result=json.loads(row.result_json) if row.result_json else None,
                error=row.error_text,
            )

    def close(self) -> None:
        self.engine.dispose()
