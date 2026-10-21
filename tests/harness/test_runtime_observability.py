from __future__ import annotations

import json

import pytest

from react_agent.harness import (
    ObservabilityArtifactError,
    RetentionPolicy,
    RuntimeEpisode,
    RuntimeObservability,
    StopReason,
    UNKNOWN,
)


def _episode() -> RuntimeEpisode:
    episode = RuntimeEpisode.start(
        "inspect token sk-123456789012",
        "react",
        runtime_episode_id="runtime-1",
        trace_id="trace-1",
        session_id="session-1",
        run_id="run-1",
        evaluation_episode_id="eval-1",
        environment={"api_key": "sk-123456789012", "model": "offline"},
    )
    return episode.finish(
        trajectory={
            "session_id": "session-1",
            "query": "inspect token sk-123456789012",
            "steps": [
                {
                    "step": 1,
                    "action": {"name": "lookup", "arguments": '{"token":"sk-123456789012"}'},
                    "observation": "ok",
                }
            ],
            "final_answer": "ok",
        },
        stop_reason=StopReason.COMPLETED,
        metrics={"steps": 1, "tool_calls": 0},
    )


def test_observability_emits_redacted_reconstructable_artifact(tmp_path):
    exported = []
    observer = RuntimeObservability(
        retention=RetentionPolicy(retention_days=7),
        exporter=exported.append,
    )
    path = tmp_path / "runtime.json"
    artifact = observer.emit(_episode(), path=path, emitted_at=1000.0)

    assert artifact["schema_version"] == "runtime-observability/v1"
    assert artifact["links"]["evaluation_episode_id"] == "eval-1"
    assert artifact["metrics"]["tool_calls"] == 0
    assert artifact["metrics"]["retry_count"] == UNKNOWN
    assert artifact["retention"] == {"retention_days": 7, "expires_at": 605800.0}
    assert artifact["runtime_episode"]["environment"]["api_key"] == "<redacted>"
    assert artifact["runtime_episode"]["trajectory"]["session_id"] == "session-1"
    assert artifact["runtime_episode"]["trajectory"]["steps"][0]["action"]["arguments"] != '{"token":"sk-123456789012"}'
    assert len(exported) == 1
    assert json.loads(path.read_text(encoding="utf-8")) == artifact

    restored = RuntimeObservability.load(path)
    assert restored.runtime_episode_id == "runtime-1"
    assert restored.evaluation_episode_id == "eval-1"
    assert restored.metrics["retry_count"] == UNKNOWN


def test_observability_rejects_tampered_links_and_metrics():
    observer = RuntimeObservability()
    artifact = observer.emit(_episode(), emitted_at=1000.0)

    tampered_link = json.loads(json.dumps(artifact))
    tampered_link["links"]["trace_id"] = "trace-other"
    with pytest.raises(ObservabilityArtifactError, match="trace_id"):
        observer.reconstruct(tampered_link)

    tampered_metrics = json.loads(json.dumps(artifact))
    tampered_metrics["metrics"]["tool_calls"] = 99
    with pytest.raises(ObservabilityArtifactError, match="metrics"):
        observer.reconstruct(tampered_metrics)


def test_observability_does_not_turn_missing_metrics_into_zero():
    episode = RuntimeEpisode.start("q", "workflow")
    episode.finish(
        trajectory={
            "session_id": episode.session_id,
            "query": "q",
            "steps": [{"step": 1, "observation": "done"}],
            "final_answer": "done",
        }
    )
    artifact = RuntimeObservability().emit(episode, emitted_at=1000.0)
    assert artifact["metrics"]["tool_calls"] == UNKNOWN
    assert artifact["metrics"]["tokens"] == UNKNOWN
    assert artifact["metrics"]["cancelled"] == UNKNOWN


def test_observability_exporter_failure_policy_is_explicit():
    episode = _episode()

    def failing_exporter(_artifact):
        raise RuntimeError("metrics backend unavailable")

    with pytest.raises(ObservabilityArtifactError, match="exporter failed"):
        RuntimeObservability(exporter=failing_exporter).emit(episode)

    artifact = RuntimeObservability(
        exporter=failing_exporter,
        exporter_failure_policy="ignore",
    ).emit(episode)
    assert artifact["schema_version"] == "runtime-observability/v1"


def test_observability_exporter_retries_then_succeeds():
    from react_agent.harness import RetryPolicy

    calls = []

    def flaky_exporter(_artifact):
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("temporary exporter outage")

    from react_agent.harness.runtime import start_runtime_metrics, stop_runtime_metrics

    collector, token = start_runtime_metrics()
    try:
        RuntimeObservability(
        exporter=flaky_exporter,
        exporter_retry_policy=RetryPolicy(max_attempts=3, base_delay=0, jitter_ratio=0),
        ).emit(_episode())
    finally:
        stop_runtime_metrics(token)
    assert len(calls) == 3
    assert collector.retry_count == 0


def test_observability_exporter_queues_and_alerts_after_retries():
    from react_agent.harness import RetryPolicy

    queued = []
    alerts = []

    def failing_exporter(_artifact):
        raise RuntimeError("collector unavailable")

    artifact = RuntimeObservability(
        exporter=failing_exporter,
        exporter_retry_policy=RetryPolicy(max_attempts=2, base_delay=0, jitter_ratio=0),
        exporter_queue=queued.append,
        exporter_alert=alerts.append,
        exporter_failure_policy="ignore",
    ).emit(_episode())

    assert artifact["schema_version"] == "runtime-observability/v1"
    assert len(queued) == 1
    assert queued[0]["event_type"] == "observability_export_failed"
    assert queued[0]["attempts"] == 2
    assert queued[0]["queued"] is True
    assert len(alerts) == 1
    assert alerts[0]["queued"] is True


def test_runtime_metrics_collector_accumulates_retries_and_tokens():
    from react_agent.harness.runtime import (
        merge_runtime_metrics,
        start_runtime_metrics,
        stop_runtime_metrics,
    )

    collector, token = start_runtime_metrics()
    try:
        collector.record_retry()
        collector.record_tokens(4)
        collector.record_tokens(6)
        metrics = merge_runtime_metrics({})
    finally:
        stop_runtime_metrics(token)

    assert metrics["retry_count"] == 1
    assert metrics["tokens"] == 10


def test_redis_stream_exporter_publishes_artifact():
    from react_agent.harness.runtime import RedisStreamObservabilityExporter

    class FakeRedis:
        def __init__(self):
            self.calls = []

        def xadd(self, stream, fields, **options):
            self.calls.append((stream, fields, options))
            return "1-0"

    client = FakeRedis()
    exporter = RedisStreamObservabilityExporter(client=client, stream="obs", maxlen=10)
    artifact = {
        "artifact_type": "runtime_episode_observability",
        "links": {"runtime_episode_id": "r1", "trace_id": "t1"},
    }

    assert exporter(artifact) == "1-0"
    stream, fields, options = client.calls[0]
    assert stream == "obs"
    assert fields["runtime_episode_id"] == "r1"
    assert json.loads(fields["artifact"]) == artifact
    assert options == {"maxlen": 10, "approximate": True}


def test_redis_stream_exporter_preserves_failure_event_type_and_links():
    from react_agent.harness.runtime import RedisStreamObservabilityExporter

    class FakeRedis:
        def xadd(self, _stream, fields, **_options):
            self.fields = fields
            return "2-0"

    client = FakeRedis()
    exporter = RedisStreamObservabilityExporter(client=client)
    failure = {
        "event_type": "observability_export_failed",
        "artifact": {"links": {"runtime_episode_id": "r2", "trace_id": "t2"}},
    }

    exporter(failure)

    assert client.fields["event_type"] == "observability_export_failed"
    assert client.fields["runtime_episode_id"] == "r2"
    assert client.fields["trace_id"] == "t2"


def test_llm_usage_is_forwarded_to_active_runtime_collector():
    from react_agent.harness.runtime import (
        current_runtime_metrics,
        merge_runtime_metrics,
        start_runtime_metrics,
        stop_runtime_metrics,
    )
    from react_agent.llm import _record_usage

    collector, token = start_runtime_metrics()
    try:
        assert current_runtime_metrics() is collector
        _record_usage(
            {"prompt_tokens": 4, "completion_tokens": 3},
            pricing={
                "input_usd_per_million_tokens": 0.15,
                "output_usd_per_million_tokens": 0.60,
            },
        )
        metrics = merge_runtime_metrics({})
    finally:
        stop_runtime_metrics(token)

    assert metrics["tokens"] == 7
    assert metrics["input_tokens"] == 4
    assert metrics["output_tokens"] == 3
    assert metrics["estimated_cost"] == 0.0000024


def test_runtime_metrics_leave_cost_unknown_without_pricing():
    from react_agent.harness.runtime import (
        merge_runtime_metrics,
        normalize_runtime_metrics,
        start_runtime_metrics,
        stop_runtime_metrics,
    )
    from react_agent.llm import _record_usage

    collector, token = start_runtime_metrics()
    try:
        _record_usage({"prompt_tokens": 100, "completion_tokens": 50})
        metrics = merge_runtime_metrics({})
    finally:
        stop_runtime_metrics(token)

    assert metrics["tokens"] == 150
    assert metrics["input_tokens"] == 100
    assert metrics["output_tokens"] == 50
    assert normalize_runtime_metrics(metrics)["estimated_cost"] == UNKNOWN


def test_runtime_metrics_do_not_estimate_cost_from_partial_usage():
    from react_agent.harness.runtime import (
        merge_runtime_metrics,
        normalize_runtime_metrics,
        start_runtime_metrics,
        stop_runtime_metrics,
    )
    from react_agent.llm import _record_usage

    pricing = {
        "input_usd_per_million_tokens": 0.15,
        "output_usd_per_million_tokens": 0.60,
    }
    collector, token = start_runtime_metrics()
    try:
        _record_usage({"prompt_tokens": 100}, pricing=pricing)
        metrics = merge_runtime_metrics({})
    finally:
        stop_runtime_metrics(token)

    assert metrics.get("tokens") is None
    assert normalize_runtime_metrics(metrics)["estimated_cost"] == UNKNOWN


def test_provider_pricing_is_model_scoped_and_custom_is_unknown():
    import json
    from pathlib import Path

    import react_agent.llm as llm_module

    original_config = llm_module._CONFIG
    try:
        llm_module._CONFIG = json.loads(
            Path("llm_config.example.json").read_text(encoding="utf-8")
        )
        deepseek = llm_module.LLM(provider="deepseek")
        openai = llm_module.LLM(provider="openai")
        custom = llm_module.LLM(provider="custom")
    finally:
        llm_module._CONFIG = original_config

    assert deepseek.pricing["input_usd_per_million_tokens"] == 0.30
    assert deepseek.pricing["output_usd_per_million_tokens"] == 1.20
    assert openai.pricing["input_usd_per_million_tokens"] == 0.15
    assert openai.pricing["output_usd_per_million_tokens"] == 0.60
    assert custom.pricing is None


def test_runtime_metrics_counts_denied_tool_envelopes():
    from react_agent.harness.runtime import merge_runtime_metrics

    metrics = merge_runtime_metrics(
        {},
        trajectory={
            "steps": [
                {
                    "step": 1,
                    "observation": '{"error_code":"policy_denied","stop_reason":"policy_denied"}',
                },
                {"step": 2, "observation": "ok"},
            ]
        },
    )

    assert metrics["denied"] == 1
