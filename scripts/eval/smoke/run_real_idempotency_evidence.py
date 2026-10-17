"""Verify shared idempotency against the project's real PostgreSQL and Redis services.

The smoke uses two independent processes and unique temporary keys. PostgreSQL
is the authority; Redis is exercised as a completed-result cache and then
intentionally bypassed to prove PostgreSQL replay and cache failure fallback.
All rows and cache entries created by this run are removed before exit.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

_SCRIPT_ROOT = Path(__file__).resolve()
_candidates = [Path.cwd()]
if len(_SCRIPT_ROOT.parents) > 3:
    _candidates.insert(0, _SCRIPT_ROOT.parents[3])
REPO_ROOT = next(
    (candidate for candidate in _candidates if (candidate / "src" / "react_agent").is_dir()),
    Path.cwd(),
)
sys.path.insert(0, str(REPO_ROOT / "src"))


def _worker(
    database_url: str,
    redis_url: str,
    key: str,
    side_effect_path: str,
    result_queue: Any,
) -> None:
    # This smoke isolates distributed idempotency; tool permission behavior is
    # covered by the runtime permission tests and would otherwise gate the
    # synthetic side-effect function behind human approval.
    os.environ["REACT_AGENT_PERMISSION_GATE"] = "0"
    from react_agent.harness import IdempotencyPolicy, PostgresIdempotencyStore, ToolBoundary

    store = PostgresIdempotencyStore(
        database_url,
        redis_url=redis_url,
        claim_lease_seconds=10,
        wait_timeout_seconds=20,
        poll_interval_seconds=0.02,
    )

    def side_effect(value: str) -> dict[str, str]:
        with open(side_effect_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"value": value}) + "\n")
        time.sleep(0.3)
        return {"value": value}

    boundary = ToolBoundary(
        {"side_effect": side_effect},
        definitions=[
            {
                "name": "side_effect",
                "idempotency_level": "required",
                "parameters": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                },
            }
        ],
        idempotency_policy=IdempotencyPolicy("required"),
        idempotency_store=store,
    )
    try:
        result_queue.put({"ok": True, "result": boundary.execute(
            "side_effect", {"value": "same"}, idempotency_key=key
        )})
    except Exception as exc:  # pragma: no cover - reported by parent
        result_queue.put({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
    finally:
        store.close()


def _cleanup(store: Any, keys: list[str], redis_client: Any) -> None:
    with store.engine.begin() as connection:
        connection.execute(store._records.delete().where(store._records.c.idempotency_key.in_(keys)))
    for key in keys:
        try:
            redis_client.delete(store._cache_key(key))
        except Exception:
            pass


def _redact_url(value: str) -> str:
    """Keep service routing evidence without persisting credentials."""
    parsed = urlsplit(value)
    if not parsed.hostname:
        return value
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def run(database_url: str, redis_url: str, output: Path) -> dict[str, Any]:
    from react_agent.harness import IdempotencyConflict, PostgresIdempotencyStore

    import redis

    prefix = f"harness-real-smoke-{uuid.uuid4().hex}"
    concurrent_key = f"{prefix}-concurrent"
    lease_key = f"{prefix}-lease"
    conflict_key = f"{prefix}-conflict"
    keys = [concurrent_key, lease_key, conflict_key]
    side_effect_path = output.with_suffix(".side-effects.jsonl")
    side_effect_path.parent.mkdir(parents=True, exist_ok=True)
    side_effect_path.unlink(missing_ok=True)
    store = PostgresIdempotencyStore(
        database_url,
        redis_url=redis_url,
        claim_lease_seconds=1,
        wait_timeout_seconds=10,
        poll_interval_seconds=0.02,
    )
    redis_client = redis.Redis.from_url(redis_url, decode_responses=True)
    checks: dict[str, bool] = {}
    details: dict[str, Any] = {}
    try:
        ctx = mp.get_context("spawn")
        result_queue = ctx.Queue()
        processes = [
            ctx.Process(
                target=_worker,
                args=(database_url, redis_url, concurrent_key, str(side_effect_path), result_queue),
            )
            for _ in range(2)
        ]
        for process in processes:
            process.start()
        results = [result_queue.get(timeout=30) for _ in processes]
        for process in processes:
            process.join(timeout=30)
        lines = side_effect_path.read_text(encoding="utf-8").splitlines() if side_effect_path.exists() else []
        checks["two_independent_processes_completed"] = all(item.get("ok") for item in results)
        checks["single_side_effect_under_concurrency"] = len(lines) == 1
        checks["same_replayed_result"] = len({json.dumps(item.get("result"), sort_keys=True) for item in results}) == 1
        details["concurrent_results"] = results
        details["side_effect_count"] = len(lines)

        completed = store.get_completed(concurrent_key)
        if completed is None:
            checks["postgres_replay_after_redis_eviction"] = False
            checks["redis_cache_refilled_after_postgres_replay"] = False
            checks["postgres_replay_when_redis_unavailable"] = False
        else:
            redis_client.delete(store._cache_key(concurrent_key))
            checks["postgres_replay_after_redis_eviction"] = store.claim_idempotency(
                concurrent_key, completed[0]
            )[0] == "replay"
            checks["redis_cache_refilled_after_postgres_replay"] = redis_client.get(
                store._cache_key(concurrent_key)
            ) is not None

            broken_cache = PostgresIdempotencyStore(
                database_url,
                redis_url="redis://127.0.0.1:6399/0",
                claim_lease_seconds=1,
                wait_timeout_seconds=5,
                poll_interval_seconds=0.02,
            )
            try:
                checks["postgres_replay_when_redis_unavailable"] = broken_cache.claim_idempotency(
                    concurrent_key, completed[0]
                )[0] == "replay"
            finally:
                broken_cache.close()

        state, _ = store.claim_idempotency(lease_key, "lease-payload")
        time.sleep(1.1)
        takeover_store = PostgresIdempotencyStore(
            database_url,
            redis_url=redis_url,
            claim_lease_seconds=1,
            wait_timeout_seconds=2,
            poll_interval_seconds=0.02,
        )
        try:
            takeover, _ = takeover_store.claim_idempotency(lease_key, "lease-payload")
        finally:
            takeover_store.close()
        checks["expired_claim_can_be_taken_over"] = state == "claimed" and takeover == "claimed"

        conflict_state, _ = store.claim_idempotency(conflict_key, "payload-a")
        try:
            store.claim_idempotency(conflict_key, "payload-b")
        except IdempotencyConflict:
            conflict_rejected = True
        else:
            conflict_rejected = False
        checks["payload_conflict_rejected"] = conflict_state == "claimed" and conflict_rejected
    finally:
        _cleanup(store, keys, redis_client)
        store.close()
        side_effect_path.unlink(missing_ok=True)

    report = {
        "schema_version": "harness-real-idempotency-evidence/v1",
        "database": _redact_url(database_url),
        "redis": _redact_url(redis_url),
        "checks": checks,
        "details": details,
        "passed": bool(checks) and all(checks.values()),
        "evidence_boundary": (
            "Real PostgreSQL and Redis services were used. Keys and rows created by this smoke "
            "were removed before exit; this is integration evidence, not an exactly-once guarantee "
            "for external side effects."
        ),
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=os.environ.get(
        "REACT_AGENT_DATABASE_URL", "postgresql+psycopg://learn:dev-password@127.0.0.1:5432/learn"
    ))
    parser.add_argument("--redis-url", default=os.environ.get(
        "REACT_AGENT_IDEMPOTENCY_REDIS_URL", "redis://127.0.0.1:6379/0"
    ))
    parser.add_argument("--output", type=Path, default=Path("artifacts/harness/real-idempotency-evidence.json"))
    args = parser.parse_args()
    report = run(args.database_url, args.redis_url, args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
