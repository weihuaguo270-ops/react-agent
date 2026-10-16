"""Shared PostgreSQL-backed idempotency with an optional Redis cache."""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from sqlalchemy import Column, DateTime, Float, MetaData, String, Table, Text, create_engine, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.engine import Engine
from sqlalchemy.dialects.postgresql import insert as pg_insert


class IdempotencyConflict(ValueError):
    """The same key was used with a different payload."""


class PostgresIdempotencyStore:
    """Authoritative idempotency ledger with an optional Redis read cache.

    PostgreSQL owns the state transition. Redis only stores completed results;
    cache failures fall back to PostgreSQL and never authorize a new side effect.
    A pending claim has a lease so a crashed worker can be replaced safely.
    """

    def __init__(
        self,
        url: str | None = None,
        *,
        engine: Engine | None = None,
        redis_client: Any | None = None,
        redis_url: str | None = None,
        cache_ttl_seconds: int = 300,
        claim_lease_seconds: float = 120.0,
        wait_timeout_seconds: float = 130.0,
        poll_interval_seconds: float = 0.05,
    ) -> None:
        resolved_url = (
            url
            or os.environ.get("REACT_AGENT_DATABASE_URL")
            or os.environ.get("REACT_AGENT_POSTGRES_URL")
        )
        if engine is None and not resolved_url:
            raise ValueError(
                "REACT_AGENT_DATABASE_URL or REACT_AGENT_POSTGRES_URL is required"
            )
        self._engine = engine or create_engine(resolved_url, pool_pre_ping=True)
        if self._engine.dialect.name not in {"postgresql", "sqlite"}:
            raise ValueError("idempotency storage requires PostgreSQL or SQLite")
        if cache_ttl_seconds < 1 or claim_lease_seconds <= 0 or wait_timeout_seconds <= 0:
            raise ValueError("invalid idempotency timing configuration")
        self.cache_ttl_seconds = int(cache_ttl_seconds)
        self.claim_lease_seconds = float(claim_lease_seconds)
        self.wait_timeout_seconds = float(wait_timeout_seconds)
        self.poll_interval_seconds = max(0.01, float(poll_interval_seconds))
        self._cache = redis_client
        if self._cache is None and redis_url:
            try:
                import redis

                self._cache = redis.Redis.from_url(redis_url, decode_responses=True)
            except (ImportError, ValueError):
                self._cache = None
        self._metadata = MetaData()
        self._records = Table(
            "react_agent_idempotency",
            self._metadata,
            Column("idempotency_key", String(255), primary_key=True),
            Column("payload_hash", String(128), nullable=False),
            Column("status", String(16), nullable=False),
            Column("owner_token", String(64), nullable=True),
            Column("lease_until", Float, nullable=True),
            Column("result_json", Text, nullable=True),
            Column("error_text", String(1000), nullable=True),
            Column("created_at", Float, nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
        )
        self._metadata.create_all(self._engine, checkfirst=True)
        self._claims: dict[tuple[int, str], str] = {}
        self._claims_lock = threading.Lock()

    @property
    def engine(self) -> Engine:
        return self._engine

    def _cache_key(self, key: str) -> str:
        return f"react-agent:idempotency:{key}"

    def _cache_get(self, key: str, payload_hash: str) -> Any:
        if self._cache is None:
            return _MISSING
        try:
            raw = self._cache.get(self._cache_key(key))
            if raw is None:
                return _MISSING
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            item = json.loads(raw) if isinstance(raw, str) else raw
            if not isinstance(item, Mapping) or item.get("payload_hash") != payload_hash:
                if isinstance(item, Mapping) and item.get("payload_hash"):
                    raise IdempotencyConflict("idempotency key conflicts with a different payload")
                return _MISSING
            return item.get("result")
        except IdempotencyConflict:
            raise
        except Exception:
            return _MISSING

    def _cache_set(self, key: str, payload_hash: str, result: Any) -> None:
        if self._cache is None:
            return
        payload = json.dumps(
            {"payload_hash": payload_hash, "result": result},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        try:
            setter = getattr(self._cache, "setex", None)
            if setter is not None:
                setter(self._cache_key(key), self.cache_ttl_seconds, payload)
            else:
                self._cache.set(self._cache_key(key), payload, ex=self.cache_ttl_seconds)
        except Exception:
            # Redis is an optimization layer; PostgreSQL remains authoritative.
            return

    def claim_idempotency(
        self,
        key: str,
        payload_hash: str,
        *,
        replay_behavior: str = "return_cached",
    ) -> tuple[str, Any | None]:
        """Atomically claim a key or return a completed result.

        Returns ``("claimed", None)`` for the caller allowed to execute and
        ``("replay", result)`` for a completed call.
        """
        cached = self._cache_get(key, payload_hash)
        if cached is not _MISSING and replay_behavior == "return_cached":
            return "replay", cached
        if cached is not _MISSING and replay_behavior == "reject":
            raise ValueError("idempotent replay rejected")
        deadline = time.monotonic() + self.wait_timeout_seconds
        owner = uuid.uuid4().hex
        claim_key = (threading.get_ident(), key)
        while True:
            now = time.time()
            wait = False
            try:
                with self._engine.begin() as connection:
                    row = connection.execute(
                        select(self._records).where(self._records.c.idempotency_key == key)
                    ).mappings().first()
                    if row is None:
                        values = {
                            "idempotency_key": key,
                            "payload_hash": payload_hash,
                            "status": "pending",
                            "owner_token": owner,
                            "lease_until": now + self.claim_lease_seconds,
                            "created_at": now,
                            "updated_at": datetime.now(timezone.utc),
                        }
                        if self._engine.dialect.name == "postgresql":
                            connection.execute(pg_insert(self._records).values(**values))
                        else:
                            from sqlalchemy.dialects.sqlite import insert as sqlite_insert

                            connection.execute(sqlite_insert(self._records).values(**values))
                        with self._claims_lock:
                            self._claims[claim_key] = owner
                        return "claimed", None
                    if str(row["payload_hash"]) != payload_hash:
                        raise IdempotencyConflict(
                            "idempotency key conflicts with a different payload"
                        )
                    if row["status"] == "completed":
                        if replay_behavior == "reject":
                            raise ValueError("idempotent replay rejected")
                        if replay_behavior == "execute":
                            changed = connection.execute(
                                update(self._records)
                                .where(
                                    self._records.c.idempotency_key == key,
                                    self._records.c.status == "completed",
                                )
                                .values(
                                    status="pending",
                                    owner_token=owner,
                                    lease_until=now + self.claim_lease_seconds,
                                    result_json=None,
                                    updated_at=datetime.now(timezone.utc),
                                )
                            )
                            if changed.rowcount == 1:
                                with self._claims_lock:
                                    self._claims[claim_key] = owner
                                return "claimed", None
                        result = json.loads(row["result_json"] or "null")
                        self._cache_set(key, payload_hash, result)
                        return "replay", result
                    if row["lease_until"] is None or float(row["lease_until"]) <= now:
                        changed = connection.execute(
                            update(self._records)
                            .where(
                                self._records.c.idempotency_key == key,
                                self._records.c.payload_hash == payload_hash,
                                self._records.c.lease_until == row["lease_until"],
                            )
                            .values(
                                status="pending",
                                owner_token=owner,
                                lease_until=now + self.claim_lease_seconds,
                                updated_at=datetime.now(timezone.utc),
                            )
                        )
                        if changed.rowcount == 1:
                            with self._claims_lock:
                                self._claims[claim_key] = owner
                            return "claimed", None
                    else:
                        wait = True
            except IntegrityError:
                # Another instance inserted the same key between our SELECT
                # and INSERT. Re-read it on the next loop iteration.
                wait = True
            if not wait or time.monotonic() >= deadline:
                raise TimeoutError("timed out waiting for idempotency claim")
            time.sleep(self.poll_interval_seconds)

    def record_idempotency(self, key: str, payload_hash: str, result: Any) -> None:
        try:
            json.dumps(result, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("idempotency result must be JSON serializable") from exc
        claim_key = (threading.get_ident(), key)
        with self._claims_lock:
            owner = self._claims.get(claim_key)
        if not owner:
            raise RuntimeError("idempotency result has no active claim")
        with self._engine.begin() as connection:
            changed = connection.execute(
                update(self._records)
                .where(
                    self._records.c.idempotency_key == key,
                    self._records.c.payload_hash == payload_hash,
                    self._records.c.status == "pending",
                    self._records.c.owner_token == owner,
                )
                .values(
                    status="completed",
                    owner_token=None,
                    lease_until=None,
                    result_json=json.dumps(result, ensure_ascii=False),
                    updated_at=datetime.now(timezone.utc),
                )
            )
        with self._claims_lock:
            self._claims.pop(claim_key, None)
        if changed.rowcount != 1:
            raise RuntimeError("idempotency claim was lost before result commit")
        self._cache_set(key, payload_hash, result)

    def get_completed(self, key: str) -> tuple[str, Any] | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                select(self._records).where(
                    self._records.c.idempotency_key == key,
                    self._records.c.status == "completed",
                )
            ).mappings().first()
        if row is None:
            return None
        return str(row["payload_hash"]), json.loads(row["result_json"] or "null")

    def close(self) -> None:
        self._engine.dispose()


class _Missing:
    pass


_MISSING = _Missing()


__all__ = ["IdempotencyConflict", "PostgresIdempotencyStore"]
