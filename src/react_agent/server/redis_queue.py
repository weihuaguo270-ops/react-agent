"""Redis Streams queue used by the distributed task MVP."""
from __future__ import annotations

import json
import os
import socket
import uuid
from typing import Any


class RedisTaskQueue:
    """Small Redis Streams adapter with a consumer group.

    The stream carries only a task id and JSON payload. Durable task state and
    results remain in PostgreSQL, so Redis can be rebuilt without losing the
    task history.
    """

    def __init__(
        self,
        url: str | None = None,
        *,
        stream: str | None = None,
        group: str | None = None,
        consumer: str | None = None,
        client: Any | None = None,
    ):
        self.stream = stream or os.environ.get("REACT_AGENT_QUEUE_NAME", "react-agent:tasks")
        self.group = group or os.environ.get("REACT_AGENT_QUEUE_GROUP", "react-agent-workers")
        self.consumer = consumer or os.environ.get(
            "REACT_AGENT_QUEUE_CONSUMER", f"worker-{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
        )
        self._cancel_prefix = f"{self.stream}:cancel:"
        self._claim_cursor = "0-0"
        self._client = client
        if self._client is None:
            try:
                import redis
            except ImportError as exc:
                raise RuntimeError("install react-agent[redis] to use the Redis queue") from exc
            redis_url = url or os.environ.get("REACT_AGENT_REDIS_URL")
            if not redis_url:
                raise ValueError("REACT_AGENT_REDIS_URL is required for Redis task storage")
            self._client = redis.Redis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=float(os.environ.get("REACT_AGENT_REDIS_CONNECT_TIMEOUT", "3")),
                socket_timeout=max(10, float(os.environ.get("REACT_AGENT_REDIS_SOCKET_TIMEOUT", "10"))),
            )
        self.ensure_group()

    @property
    def client(self) -> Any:
        return self._client

    def ensure_group(self) -> None:
        try:
            self.client.xgroup_create(self.stream, self.group, id="0-0", mkstream=True)
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def enqueue(self, task_id: str, payload: dict[str, Any]) -> str:
        # Admission and append share one Redis transaction. Never trim work
        # that has not been delivered/acknowledged just to cap stream history.
        result = self.client.eval(
            """
            local groups = redis.call('XINFO', 'GROUPS', KEYS[1])
            for _, g in ipairs(groups) do
                local name, pending, lag
                for i = 1, #g, 2 do
                    if g[i] == 'name' then name = g[i+1] end
                    if g[i] == 'pending' then pending = g[i+1] end
                    if g[i] == 'lag' then lag = g[i+1] end
                end
                if name == ARGV[1] then
                    if pending + (tonumber(lag) or redis.call('XLEN', KEYS[1])) >= tonumber(ARGV[2]) then
                        return false
                    end
                    return redis.call('XADD', KEYS[1], '*', 'task_id', ARGV[3], 'payload', ARGV[4])
                end
            end
            return redis.error_reply('consumer group missing')
            """,
            1, self.stream, self.group,
            int(os.environ.get("REACT_AGENT_QUEUE_MAX_TASKS", "10000")),
            task_id, json.dumps(payload, ensure_ascii=False),
        )
        if not result:
            raise RuntimeError("task queue is full")
        return str(result)

    def read(self, *, block_ms: int = 5000) -> tuple[str, str, dict[str, Any]] | None:
        rows = self.client.xreadgroup(
            self.group, self.consumer, {self.stream: ">"}, count=1, block=min(block_ms, 5000),
        )
        if not rows:
            return None
        _, messages = rows[0]
        if not messages:
            return None
        message_id, fields = messages[0]
        return str(message_id), str(fields["task_id"]), json.loads(fields["payload"])

    def claim_pending(self) -> tuple[str, str, dict[str, Any]] | None:
        """Reclaim messages idle longer than the visibility timeout."""
        idle_ms = int(os.environ.get("REACT_AGENT_QUEUE_VISIBILITY_MS", "900000"))
        try:
            result = self.client.xautoclaim(
                self.stream,
                self.group,
                self.consumer,
                min_idle_time=idle_ms,
                start_id=self._claim_cursor,
                count=1,
            )
        except (AttributeError, NotImplementedError):
            return None
        messages = result[1] if isinstance(result, (list, tuple)) else result.get("messages", [])
        self._claim_cursor = str(result[0]) if isinstance(result, (list, tuple)) else "0-0"
        if not messages:
            return None
        message_id, fields = messages[0]
        return str(message_id), str(fields["task_id"]), json.loads(fields["payload"])

    def ack(self, message_id: str) -> None:
        self.client.eval(
            "local n = redis.call('XACK', KEYS[1], ARGV[1], ARGV[2]); "
            "redis.call('XDEL', KEYS[1], ARGV[2]); return n",
            1, self.stream, self.group, message_id,
        )

    def request_cancel(self, task_id: str, *, ttl_seconds: int = 86400) -> None:
        self.client.set(f"{self._cancel_prefix}{task_id}", "1", ex=ttl_seconds)

    def is_cancelled(self, task_id: str) -> bool:
        return bool(self.client.exists(f"{self._cancel_prefix}{task_id}"))

    def queue_length(self) -> int:
        """Return active work, excluding already acknowledged stream history."""
        try:
            pending = self.client.xpending(self.stream, self.group)
            pending_count = 0
            if isinstance(pending, dict):
                pending_count = int(pending.get("pending", 0))
            elif pending:
                pending_count = int(pending[0])
            # Redis 7 exposes the consumer-group lag through XINFO GROUPS.
            # Include it so queued, not-yet-delivered messages count toward
            # the limit while acknowledged stream history does not.
            groups = self.client.xinfo_groups(self.stream)
            for group in groups:
                name = group.get("name")
                if isinstance(name, bytes):
                    name = name.decode()
                if name == self.group:
                    return pending_count + int(group.get("lag") or 0)
            return pending_count
        except Exception:
            # Older Redis clients may not expose XINFO GROUPS.  xlen is a
            # conservative fallback that still enforces a finite bound.
            return int(self.client.xlen(self.stream))

    def close(self) -> None:
        close = getattr(self.client, "close", None)
        if close:
            close()
