from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.calls = []

    def get(self, key):
        self.calls.append(("get", key))
        return self.values.get(key)

    def setex(self, key, ttl, value):
        self.calls.append(("setex", key, ttl))
        self.values[key] = value


def _store(path, redis_client=None):
    from react_agent.harness import PostgresIdempotencyStore

    return PostgresIdempotencyStore(
        f"sqlite:///{path}",
        redis_client=redis_client,
        claim_lease_seconds=2,
        wait_timeout_seconds=5,
        poll_interval_seconds=0.01,
    )


def test_postgres_store_is_authoritative_and_redis_is_cache(tmp_path):
    from react_agent.harness import IdempotencyPolicy, ToolBoundary

    redis = FakeRedis()
    store_path = tmp_path / "idempotency.sqlite"
    calls = []

    def write_once(value):
        calls.append(value)
        return {"written": value}

    first = ToolBoundary(
        {"write_once": write_once},
        definitions=[{"name": "write_once", "idempotency_level": "required"}],
        idempotency_policy=IdempotencyPolicy("required"),
        idempotency_store=_store(store_path, redis),
    )
    assert first.execute("write_once", {"value": "ok"}, idempotency_key="k1") == {
        "written": "ok"
    }
    assert calls == ["ok"]

    second_store = _store(store_path, redis)
    second = ToolBoundary(
        {"write_once": write_once},
        definitions=[{"name": "write_once", "idempotency_level": "required"}],
        idempotency_policy=IdempotencyPolicy("required"),
        idempotency_store=second_store,
    )
    assert second.execute("write_once", {"value": "ok"}, idempotency_key="k1") == {
        "written": "ok"
    }
    assert calls == ["ok"]
    assert any(call[0] == "setex" for call in redis.calls)
    with pytest.raises(ValueError, match="conflicts"):
        second.execute("write_once", {"value": "changed"}, idempotency_key="k1")
    first._idempotency_results.close()
    second_store.close()


def test_postgres_store_serializes_same_key_across_threads(tmp_path):
    from react_agent.harness import IdempotencyPolicy, ToolBoundary

    store = _store(tmp_path / "concurrent.sqlite")
    calls = []
    barrier = threading.Barrier(2)

    def write_once():
        calls.append(1)
        time.sleep(0.08)
        return {"count": len(calls)}

    def run():
        boundary = ToolBoundary(
            {"write_once": write_once},
            definitions=[{"name": "write_once", "idempotency_level": "required"}],
            idempotency_policy=IdempotencyPolicy("required"),
            idempotency_store=store,
        )
        barrier.wait()
        return boundary.execute("write_once", {}, idempotency_key="same-key")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _item: run(), range(2)))

    assert results == [{"count": 1}, {"count": 1}]
    assert len(calls) == 1
    store.close()


def test_postgres_store_reclaims_expired_claim(tmp_path):
    from react_agent.harness import PostgresIdempotencyStore

    store = _store(tmp_path / "lease.sqlite")
    state, _ = store.claim_idempotency("lease-key", "hash-1")
    assert state == "claimed"
    time.sleep(2.05)
    state, _ = store.claim_idempotency("lease-key", "hash-1")
    assert state == "claimed"
    store.close()
