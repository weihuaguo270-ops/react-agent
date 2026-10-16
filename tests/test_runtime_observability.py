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
