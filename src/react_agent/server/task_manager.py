"""异步任务管理。

默认使用进程内线程池；设置 ``REACT_AGENT_TASK_STORE=mysql`` 后，任务状态写入
MySQL。线程执行器仍是单实例调度器，不等同于分布式消息队列。
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import quote, urlparse


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


class MySQLTaskStore:
    """将任务状态持久化到 MySQL；未显式启用时不加载驱动。"""

    def __init__(self, url: str | None = None):
        url = url or os.environ.get("REACT_AGENT_MYSQL_URL") or os.environ.get("MYSQL_URL")
        if not url and os.environ.get("MYSQL_HOST") and os.environ.get("MYSQL_DATABASE"):
            user = quote(os.environ.get("MYSQL_USER", "root"), safe="")
            password = quote(os.environ.get("MYSQL_PASSWORD", ""), safe="")
            host = os.environ["MYSQL_HOST"]
            port = os.environ.get("MYSQL_PORT", "3306")
            database = os.environ["MYSQL_DATABASE"]
            url = f"mysql://{user}:{password}@{host}:{port}/{database}"
        if not url:
            raise ValueError(
                "REACT_AGENT_MYSQL_URL/MYSQL_URL or MYSQL_HOST+MYSQL_DATABASE is required"
            )
        try:
            import pymysql
        except ImportError as exc:
            raise RuntimeError("install react-agent[mysql] to use MySQL task storage") from exc
        parsed = urlparse(url)
        if parsed.scheme not in {"mysql", "mysql+pymysql"} or not parsed.hostname or not parsed.path.strip("/"):
            raise ValueError("MySQL URL must include mysql scheme, host and database")
        self._pymysql = pymysql
        self._dsn = {
            "host": parsed.hostname,
            "port": parsed.port or 3306,
            "user": parsed.username or "root",
            "password": parsed.password or "",
            "database": parsed.path.strip("/"),
            "charset": "utf8mb4",
            "autocommit": True,
        }
        self.setup()

    def _connect(self):
        return self._pymysql.connect(**self._dsn)

    def setup(self):
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS react_agent_tasks (
                        task_id VARCHAR(64) PRIMARY KEY,
                        status VARCHAR(32) NOT NULL,
                        created_at DOUBLE NOT NULL,
                        started_at DOUBLE NULL,
                        finished_at DOUBLE NULL,
                        result_json LONGTEXT NULL,
                        error_text VARCHAR(1000) NULL,
                        updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                            ON UPDATE CURRENT_TIMESTAMP(6)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """)
        finally:
            connection.close()

    def save(self, record: TaskRecord):
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO react_agent_tasks
                    (task_id,status,created_at,started_at,finished_at,result_json,error_text)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE status=VALUES(status), started_at=VALUES(started_at),
                    finished_at=VALUES(finished_at), result_json=VALUES(result_json),
                    error_text=VALUES(error_text)""",
                    (record.task_id, record.status, record.created_at, record.started_at,
                     record.finished_at,
                     json.dumps(record.result, ensure_ascii=False) if record.result is not None else None,
                     record.error),
                )
        finally:
            connection.close()

    def get(self, task_id: str) -> TaskRecord | None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""SELECT task_id,status,created_at,started_at,finished_at,
                    result_json,error_text FROM react_agent_tasks WHERE task_id=%s""", (task_id,))
                row = cursor.fetchone()
        finally:
            connection.close()
        if not row:
            return None
        return TaskRecord(row[0], row[1], row[2], row[3], row[4],
                          json.loads(row[5]) if row[5] else None, row[6])


class TaskManager:
    """有界线程池任务管理器，可选 MySQL 状态持久化。"""

    def __init__(self, max_workers: int = 4, max_tasks: int = 128, store=None):
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="agent-task")
        self._max_tasks = max_tasks
        self._tasks: dict[str, TaskRecord] = {}
        self._lock = threading.RLock()
        backend = os.environ.get("REACT_AGENT_TASK_STORE", "memory").strip().lower()
        self._store = store or (MySQLTaskStore() if backend == "mysql" else None)

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


task_manager = TaskManager()
