"""Task manager backed by Redis Streams and PostgreSQL."""
from __future__ import annotations

import os
import time
import uuid
from typing import TYPE_CHECKING, Any

from react_agent.server.redis_queue import RedisTaskQueue
from react_agent.server.sqlalchemy_store import PostgreSQLTaskStore
if TYPE_CHECKING:
    from react_agent.server.task_manager import TaskRecord


class RedisTaskManager:
    """API-side task manager: persist, enqueue, query and request cancellation."""

    def __init__(self, *, store: Any | None = None, queue: RedisTaskQueue | None = None):
        self._store = store or PostgreSQLTaskStore()
        self._queue = queue or RedisTaskQueue()
        self._max_queue = int(os.environ.get("REACT_AGENT_QUEUE_MAX_TASKS", "10000"))

    def submit_payload(self, body: dict[str, Any], request_id: str) -> TaskRecord:
        from react_agent.server.task_manager import TaskRecord

        try:
            queue_length = self._queue.queue_length()
        except Exception as exc:
            raise RuntimeError("task queue is unavailable") from exc
        if queue_length >= self._max_queue:
            raise RuntimeError("task queue is full")
        record = TaskRecord(task_id=uuid.uuid4().hex)
        self._store.save(record)
        try:
            self._queue.enqueue(
                record.task_id,
                {"body": body, "request_id": request_id},
            )
        except Exception as exc:
            record.status = "failed"
            record.error = "unable to enqueue task"
            record.finished_at = time.time()
            self._store.save(record)
            if isinstance(exc, RuntimeError) and str(exc) == "task queue is full":
                raise
            raise RuntimeError("task queue is unavailable") from exc
        return record

    def get(self, task_id: str) -> TaskRecord | None:
        return self._store.get(task_id)

    def cancel(self, task_id: str) -> TaskRecord | None:
        record = self._store.get(task_id)
        if record is None:
            return None
        if record.status in {"queued", "running", "retry_wait"}:
            self._queue.request_cancel(task_id)
            record = self._store.cancel(task_id)
        return record

    def shutdown(self, wait: bool = True) -> None:
        del wait
        close = getattr(self._store, "close", None)
        if close:
            close()
        self._queue.close()
