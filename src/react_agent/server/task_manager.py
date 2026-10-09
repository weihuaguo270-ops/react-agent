"""异步任务管理。

默认使用进程内线程池；任务状态可选持久化到 PostgreSQL。
线程执行器仍是单实例调度器，不等同于分布式消息队列。
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class TaskRecord:
    task_id: str
    status: str = "queued"
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    result: Any = None
    error: str | None = None
    future: Future | None = field(default=None, repr=False)

    def public(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "result": self.result,
            "error": self.error,
        }


class TaskManager:
    """有界线程池任务管理器，可选 PostgreSQL 状态持久化。"""

    def __init__(self, max_workers: int = 4, max_tasks: int = 128, store=None):
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="agent-task")
        self._max_tasks = max_tasks
        self._tasks: dict[str, TaskRecord] = {}
        self._lock = threading.RLock()
        backend = os.environ.get("REACT_AGENT_TASK_STORE", "memory").strip().lower()
        if store is not None:
            self._store = store
        elif backend in {"postgresql", "postgres", "sqlalchemy"}:
            from react_agent.server.sqlalchemy_store import PostgreSQLTaskStore

            self._store = PostgreSQLTaskStore()
        elif backend == "memory":
            self._store = None
        else:
            raise ValueError(f"unsupported task store: {backend}")

    def _persist(self, record: TaskRecord) -> None:
        if self._store:
            self._store.save(record)

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> TaskRecord:
        with self._lock:
            active = sum(t.status in {"queued", "running"} for t in self._tasks.values())
            if active >= self._max_tasks:
                raise RuntimeError("task queue is full")
            record = TaskRecord(task_id=uuid.uuid4().hex)
            self._tasks[record.task_id] = record
            self._persist(record)
            record.future = self._executor.submit(self._run, record.task_id, fn, args, kwargs)
            return record

    def _run(self, task_id: str, fn: Callable[..., Any], args: tuple, kwargs: dict) -> None:
        with self._lock:
            record = self._tasks[task_id]
            if record.status == "cancelled":
                return
            record.status = "running"
            record.started_at = time.time()
            self._persist(record)
        try:
            result = fn(*args, **kwargs)
        except Exception as exc:  # worker 错误必须回写任务状态，不能让查询端卡住
            with self._lock:
                record.status = "failed"
                record.error = str(exc)[:500]
                record.finished_at = time.time()
                self._persist(record)
        else:
            with self._lock:
                if record.status != "cancelled":
                    record.status = "succeeded"
                    record.result = result
                record.finished_at = time.time()
                self._persist(record)

    def get(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            record = self._tasks.get(task_id)
            if record is None and self._store:
                record = self._store.get(task_id)
            return record

    def cancel(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            record = self._tasks.get(task_id)
            if record is None:
                return None
            if record.status == "queued" and record.future and record.future.cancel():
                record.status = "cancelled"
                record.finished_at = time.time()
            elif record.status == "running":
                # Python 线程不能安全强杀；标记取消，执行函数自行通过超时/取消令牌退出。
                record.status = "cancelled"
            self._persist(record)
            return record

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=True)


def _build_task_manager():
    backend = os.environ.get("REACT_AGENT_QUEUE_BACKEND", "memory").strip().lower()
    if backend == "redis":
        from react_agent.server.redis_task_manager import RedisTaskManager

        return RedisTaskManager()
    return TaskManager()


task_manager = _build_task_manager()
