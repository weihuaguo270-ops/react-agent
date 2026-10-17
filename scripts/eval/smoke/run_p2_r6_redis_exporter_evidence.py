"""Verify configured observability export against the project's Compose Redis."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "artifacts" / "harness" / "p2-r6-redis-exporter.json"
REDIS_URL = "redis://127.0.0.1:6380/0"


def compose_container(service: str) -> str:
    result = subprocess.run(
        ["docker", "compose", "ps", "-q", service], cwd=ROOT,
        text=True, capture_output=True, check=True,
    )
    container = result.stdout.strip().splitlines()
    if not container:
        raise RuntimeError(f"project Compose service is not running: {service}")
    return container[0]


def main() -> int:
    import redis

    suffix = uuid.uuid4().hex[:12]
    primary_stream = f"react-agent:harness-p2-evidence:{suffix}"
    failure_stream = f"react-agent:harness-p2-failures:{suffix}"
    client = redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=3)
    client.ping()

    os.environ.update(
        {
            "REACT_AGENT_OBSERVABILITY_EXPORTER": "redis",
            "REACT_AGENT_OBSERVABILITY_REDIS_URL": REDIS_URL,
            "REACT_AGENT_OBSERVABILITY_STREAM": primary_stream,
            "REACT_AGENT_OBSERVABILITY_FAILURE_STREAM": failure_stream,
            "REACT_AGENT_OBSERVABILITY_MAXLEN": "100",
            "REACT_AGENT_OBSERVABILITY_FAILURE_MAXLEN": "100",
            "REACT_AGENT_OBSERVABILITY_RETRY_ATTEMPTS": "3",
            "REACT_AGENT_OBSERVABILITY_RETRY_BASE_DELAY": "0",
            "REACT_AGENT_OBSERVABILITY_RETRY_MAX_DELAY": "0",
            "REACT_AGENT_OBSERVABILITY_FAILURE_POLICY": "ignore",
        }
    )
    from react_agent.harness.runtime import RuntimeEpisode, configured_runtime_observability

    episode = RuntimeEpisode.start(
        "redis exporter evidence", "react", runtime_episode_id=f"p2-r6-{suffix}",
        trace_id=f"trace-{suffix}", evaluation_episode_id=f"eval-{suffix}",
    ).finish(
        trajectory={
            "session_id": f"session-{suffix}", "query": "redis exporter evidence",
            "steps": [{"step": 1, "observation": "ok"}], "final_answer": "ok",
        },
        stop_reason="completed", status="completed", metrics={"tokens": 7},
    )
    runtime_observability = configured_runtime_observability()
    local_path = ROOT / "artifacts" / "harness" / f"p2-r6-runtime-{suffix}.json"
    emitted = runtime_observability.emit(episode, path=local_path)
    primary_entries = client.xrange(primary_stream)
    primary_payload = json.loads(primary_entries[0][1]["artifact"]) if primary_entries else {}

    calls = 0

    def fail_twice_then_succeed(_artifact):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RuntimeError("injected temporary Redis exporter failure")

    from react_agent.harness.runtime import RetryPolicy, RuntimeObservability

    retry_observer = RuntimeObservability(
        exporter=fail_twice_then_succeed,
        exporter_retry_policy=RetryPolicy(
            max_attempts=3, base_delay=0, max_delay=0, jitter_ratio=0
        ),
        exporter_failure_policy="raise",
    )
    retry_observer.emit(episode)
    retry_check = calls == 3

    attempts = 0

    def always_fail(_artifact):
        nonlocal attempts
        attempts += 1
        raise RuntimeError("injected persistent exporter failure")

    failure_exporter = configured_runtime_observability()
    failure_exporter.exporter = always_fail
    failure_exporter.exporter_retry_policy = RetryPolicy(
        max_attempts=2, base_delay=0, max_delay=0, jitter_ratio=0
    )
    failure_exporter.exporter_queue = type(runtime_observability.exporter)(
        url=REDIS_URL, stream=failure_stream, maxlen=100,
        client=runtime_observability.exporter.client,
    )
    failure_exporter.emit(episode)
    failure_entries = client.xrange(failure_stream)
    failure_payload = json.loads(failure_entries[0][1]["artifact"]) if failure_entries else {}

    checks = {
        "project_redis_ping": True,
        "runtime_artifact_written_to_project_redis": bool(primary_entries),
        "runtime_links_preserved": primary_payload.get("links", {}).get("runtime_episode_id") == episode.runtime_episode_id
        and primary_payload.get("links", {}).get("evaluation_episode_id") == episode.evaluation_episode_id,
        "local_artifact_written": local_path.is_file(),
        "transient_exporter_failure_retried_to_success": retry_check,
        "persistent_failure_retried_and_queued": attempts == 2
        and failure_payload.get("event_type") == "observability_export_failed"
        and failure_payload.get("attempts") == 2
        and failure_payload.get("queued") is True,
    }
    report = {
        "schema_version": "harness-p2-r6-redis-exporter/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_head": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
            capture_output=True, check=True,
        ).stdout.strip(),
        "services": {
            "compose_project": "react-agent",
            "redis_container": "react-agent-redis-1",
            "postgres_container": "react-agent-postgres-1",
            "redis_endpoint": REDIS_URL,
        },
        "fixture": {"runtime_episode_id": episode.runtime_episode_id, "run_suffix": suffix},
        "streams": {"runtime": primary_stream, "failure": failure_stream},
        "checks": checks,
        "passed": all(checks.values()),
        "alerting": {
            "status": "deployment_callback_required",
            "detail": "The code exposes exporter_alert callback injection; this run verifies Redis failure queue only and does not claim an external notification service is configured.",
        },
        "local_artifact": {
            "path": local_path.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(local_path.read_bytes()).hexdigest(),
        },
        "evidence_boundary": "Uses the project's react-agent-redis-1 Compose service via host port 6380; unique test streams are deleted before exit.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    client.delete(primary_stream, failure_stream)
    report_bytes = (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    report["artifact_sha256"] = hashlib.sha256(report_bytes).hexdigest()
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
