"""MySQL 持久化 CheckpointSaver。

该模块只在显式配置 ``LANGGRAPH_CHECKPOINT_BACKEND=mysql`` 时导入，避免 Core
路径强制安装数据库驱动。表结构由 ``setup()`` 创建，checkpoint 和 pending
writes 使用 LangGraph serializer 编码，能保存消息、元数据和版本信息。
"""
from __future__ import annotations

import asyncio
import os
from contextlib import contextmanager
from typing import Any, Iterator
from urllib.parse import quote, urlparse

from langgraph.checkpoint.base import BaseCheckpointSaver, CheckpointTuple, WRITES_IDX_MAP


class MySQLCheckpointSaver(BaseCheckpointSaver):
    """基于 PyMySQL 的 LangGraph checkpoint 存储。"""

    def __init__(self, url: str | None = None, *, serde=None):
        super().__init__(serde=serde)
        self.url = url or os.environ.get("LANGGRAPH_MYSQL_URL") or os.environ.get("MYSQL_URL")
        if not self.url and os.environ.get("MYSQL_HOST") and os.environ.get("MYSQL_DATABASE"):
            user = quote(os.environ.get("MYSQL_USER", "root"), safe="")
            password = quote(os.environ.get("MYSQL_PASSWORD", ""), safe="")
            host = os.environ["MYSQL_HOST"]
            port = os.environ.get("MYSQL_PORT", "3306")
            database = os.environ["MYSQL_DATABASE"]
            self.url = f"mysql://{user}:{password}@{host}:{port}/{database}"
        if not self.url:
            raise ValueError(
                "LANGGRAPH_MYSQL_URL/MYSQL_URL or MYSQL_HOST+MYSQL_DATABASE is required"
            )
        try:
            import pymysql
        except ImportError as exc:
            raise RuntimeError("install react-agent[mysql] to use MySQL checkpoints") from exc
        self._pymysql = pymysql
        self._dsn = self._parse_url(self.url)
        self.setup()

    @staticmethod
    def _parse_url(url: str) -> dict[str, Any]:
        parsed = urlparse(url)
        if parsed.scheme not in {"mysql", "mysql+pymysql"}:
            raise ValueError("MySQL URL must use mysql:// or mysql+pymysql://")
        if not parsed.hostname or not parsed.path.strip("/"):
            raise ValueError("MySQL URL must include host and database")
        return {
            "host": parsed.hostname,
            "port": parsed.port or 3306,
            "user": parsed.username or "root",
            "password": parsed.password or "",
            "database": parsed.path.strip("/"),
            "charset": "utf8mb4",
            "autocommit": True,
        }

    @contextmanager
    def _connection(self):
        connection = self._pymysql.connect(**self._dsn)
        try:
            yield connection
        finally:
            connection.close()

    def setup(self) -> None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS langgraph_checkpoints (
                        seq BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                        thread_id VARCHAR(191) NOT NULL,
                        checkpoint_ns VARCHAR(191) NOT NULL DEFAULT '',
                        checkpoint_id VARCHAR(191) NOT NULL,
                        parent_checkpoint_id VARCHAR(191) NULL,
                        checkpoint_type VARCHAR(100) NOT NULL,
                        checkpoint_blob LONGBLOB NOT NULL,
                        metadata_type VARCHAR(100) NOT NULL,
                        metadata_blob LONGBLOB NOT NULL,
                        created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
                        UNIQUE KEY uq_checkpoint (thread_id, checkpoint_ns, checkpoint_id),
                        KEY ix_checkpoint_thread (thread_id, checkpoint_ns, seq)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS langgraph_writes (
                        seq BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                        thread_id VARCHAR(191) NOT NULL,
                        checkpoint_ns VARCHAR(191) NOT NULL DEFAULT '',
                        checkpoint_id VARCHAR(191) NOT NULL,
                        task_id VARCHAR(191) NOT NULL,
                        idx INT NOT NULL,
                        channel VARCHAR(191) NOT NULL,
                        value_type VARCHAR(100) NOT NULL,
                        value_blob LONGBLOB NOT NULL,
                        UNIQUE KEY uq_write (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """)

    @staticmethod
    def _config(config: dict) -> tuple[str, str, str | None]:
        configurable = config.get("configurable", {})
        return (
            str(configurable.get("thread_id") or ""),
            str(configurable.get("checkpoint_ns") or ""),
            configurable.get("checkpoint_id"),
        )

    def put(self, config, checkpoint, metadata, new_versions):
        thread_id, checkpoint_ns, _ = self._config(config)
        if not thread_id:
            raise ValueError("configurable.thread_id is required")
        checkpoint_id = checkpoint["id"]
        parent_id = config.get("configurable", {}).get("checkpoint_id")
        checkpoint_type, checkpoint_blob = self.serde.dumps_typed(checkpoint)
        metadata_type, metadata_blob = self.serde.dumps_typed(metadata)
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO langgraph_checkpoints
                    (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id,
                     checkpoint_type, checkpoint_blob, metadata_type, metadata_blob)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE checkpoint_blob=VALUES(checkpoint_blob),
                    metadata_blob=VALUES(metadata_blob)""",
                    (thread_id, checkpoint_ns, checkpoint_id, parent_id,
                     checkpoint_type, checkpoint_blob, metadata_type, metadata_blob),
                )
        return {"configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": checkpoint_ns,
            "checkpoint_id": checkpoint_id,
        }}

    def _pending_writes(self, thread_id: str, checkpoint_ns: str, checkpoint_id: str):
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT task_id, channel, value_type, value_blob
                    FROM langgraph_writes
                    WHERE thread_id=%s AND checkpoint_ns=%s AND checkpoint_id=%s
                    ORDER BY task_id, idx""",
                    (thread_id, checkpoint_ns, checkpoint_id),
                )
                rows = cursor.fetchall()
        return [
            (task_id, channel, self.serde.loads_typed((value_type, value_blob)))
            for task_id, channel, value_type, value_blob in rows
        ]

    def _row_to_tuple(self, row, *, pending_writes=None) -> CheckpointTuple:
        (thread_id, checkpoint_ns, checkpoint_id, parent_id, checkpoint_type,
         checkpoint_blob, metadata_type, metadata_blob) = row
        config = {"configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": checkpoint_ns,
            "checkpoint_id": checkpoint_id,
        }}
        parent = None if not parent_id else {"configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": checkpoint_ns,
            "checkpoint_id": parent_id,
        }}
        return CheckpointTuple(
            config=config,
            checkpoint=self.serde.loads_typed((checkpoint_type, checkpoint_blob)),
            metadata=self.serde.loads_typed((metadata_type, metadata_blob)),
            parent_config=parent,
            pending_writes=(
                self._pending_writes(thread_id, checkpoint_ns, checkpoint_id)
                if pending_writes is None else pending_writes
            ),
        )

    def get_tuple(self, config):
        thread_id, checkpoint_ns, checkpoint_id = self._config(config)
        if not thread_id:
            return None
        with self._connection() as connection:
            with connection.cursor() as cursor:
                if checkpoint_id:
                    cursor.execute(
                        """SELECT thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id,
                        checkpoint_type, checkpoint_blob, metadata_type, metadata_blob
                        FROM langgraph_checkpoints WHERE thread_id=%s AND checkpoint_ns=%s
                        AND checkpoint_id=%s""", (thread_id, checkpoint_ns, checkpoint_id))
                else:
                    cursor.execute(
                        """SELECT thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id,
                        checkpoint_type, checkpoint_blob, metadata_type, metadata_blob
                        FROM langgraph_checkpoints WHERE thread_id=%s AND checkpoint_ns=%s
                        ORDER BY seq DESC LIMIT 1""", (thread_id, checkpoint_ns))
                row = cursor.fetchone()
        return self._row_to_tuple(row) if row else None

    def list(self, config, *, filter=None, before=None, limit=None) -> Iterator[CheckpointTuple]:
        """List checkpoints with the same filtering semantics as MemorySaver."""
        config = config or {}
        configurable = config.get("configurable", {})
        thread_id = configurable.get("thread_id")
        checkpoint_ns = configurable.get("checkpoint_ns")
        checkpoint_id = configurable.get("checkpoint_id")
        before_id = (before or {}).get("configurable", {}).get("checkpoint_id")
        query = """SELECT thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id,
                   checkpoint_type, checkpoint_blob, metadata_type, metadata_blob
                   FROM langgraph_checkpoints WHERE 1=1"""
        params: list[Any] = []
        if thread_id is not None:
            query += " AND thread_id=%s"
            params.append(str(thread_id))
        if checkpoint_ns is not None:
            query += " AND checkpoint_ns=%s"
            params.append(str(checkpoint_ns))
        if checkpoint_id:
            query += " AND checkpoint_id=%s"
            params.append(str(checkpoint_id))
        if before_id:
            query += " AND checkpoint_id < %s"
            params.append(str(before_id))
        query += " ORDER BY seq DESC"
        if limit is not None:
            if limit <= 0:
                return iter(())
            query += " LIMIT %s"
            params.append(limit)
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, params)
                rows = cursor.fetchall()
        tuples = []
        for row in rows:
            item = self._row_to_tuple(row)
            if filter and not all(filter_key_value == item.metadata.get(filter_key)
                                  for filter_key, filter_key_value in filter.items()):
                continue
            tuples.append(item)
        return iter(tuples)

    def put_writes(self, config, writes, task_id, task_path="") -> None:
        thread_id, checkpoint_ns, checkpoint_id = self._config(config)
        if not checkpoint_id:
            return
        with self._connection() as connection:
            with connection.cursor() as cursor:
                for index, (channel, value) in enumerate(writes):
                    write_index = WRITES_IDX_MAP.get(channel, index)
                    value_type, value_blob = self.serde.dumps_typed(value)
                    cursor.execute(
                        """INSERT IGNORE INTO langgraph_writes
                        (thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel,
                         value_type, value_blob) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (thread_id, checkpoint_ns, checkpoint_id, task_id, write_index,
                         channel, value_type, value_blob),
                    )

    async def aget_tuple(self, config):
        return await asyncio.to_thread(self.get_tuple, config)

    async def aput(self, config, checkpoint, metadata, new_versions):
        return await asyncio.to_thread(self.put, config, checkpoint, metadata, new_versions)

    async def aput_writes(self, config, writes, task_id, task_path=""):
        await asyncio.to_thread(self.put_writes, config, writes, task_id, task_path)

    async def alist(self, config, *, filter=None, before=None, limit=None):
        rows = await asyncio.to_thread(lambda: list(self.list(config, filter=filter, before=before, limit=limit)))
        for row in rows:
            yield row
