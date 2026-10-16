from __future__ import annotations

import hashlib

import pytest

from react_agent.harness import (
    DeterministicReplay,
    ReplayFixtureUnavailable,
    ReplayIntegrityError,
    ReplayManifest,
    ReplayMode,
    ReplaySideEffectDenied,
)


def _trajectory() -> dict:
    return {
        "session_id": "replay-session",
        "query": "calculate",
        "steps": [
            {
                "step": 1,
                "action": {"name": "calculator", "arguments": '{"expression":"2+2"}'},
                "observation": "4",
            }
        ],
        "final_answer": "4",
        "metadata": {"stop_reason": "completed"},
    }


def _fixture_ref() -> tuple[dict, bytes]:
    data = b"fixture-v1"
    return (
        {
            "fixture_id": "calc-fixture",
            "version": "1",
            "data_sha256": hashlib.sha256(data).hexdigest(),
        },
        data,
    )


def test_record_manifest_round_trips_with_component_and_manifest_hashes(tmp_path):
    fixture, _ = _fixture_ref()
    manifest = DeterministicReplay.record(
        _trajectory(),
        tool_results=[{"call_id": "call-1", "result": "4"}],
        model_responses=[{"content": "4"}],
        fixture=fixture,
        manifest_id="manifest-1",
    )
    path = manifest.save(tmp_path / "manifest.json")
    restored = ReplayManifest.load(path)

    assert restored.to_dict() == manifest.to_dict()
    assert len(manifest.content_hash()) == 64
    assert manifest.to_dict()["schema_version"] == "replay-manifest/v1"


def test_replay_is_deterministic_and_fail_closed_for_network_and_side_effects():
    fixture, fixture_data = _fixture_ref()
    manifest = DeterministicReplay.record(
        _trajectory(),
        tool_results={"call-1": {"result": "4"}},
        model_responses=[{"content": "4"}],
        fixture=fixture,
    )
    runner = DeterministicReplay(fixture_loader=lambda _ref: fixture_data)

    first = runner.replay(manifest)
    second = runner.replay(manifest)

    assert first.execution_replay is True
    assert first.display_only is False
    assert first.network_allowed is False
    assert first.side_effects_allowed is False
    assert first.stop_reason == "completed"
    assert first.scoring_input_sha256 == second.scoring_input_sha256
    with pytest.raises(ReplaySideEffectDenied):
        runner.assert_network_allowed()
    with pytest.raises(ReplaySideEffectDenied):
        runner.assert_side_effect_allowed("write database")


def test_missing_fixture_is_rejected_before_replay_execution():
    manifest = DeterministicReplay.record(_trajectory())

    with pytest.raises(ReplayFixtureUnavailable):
        DeterministicReplay().replay(manifest)


def test_fixture_hash_mismatch_and_tampered_manifest_fail_closed():
    fixture, fixture_data = _fixture_ref()
    manifest = DeterministicReplay.record(_trajectory(), fixture=fixture)
    with pytest.raises(ReplayIntegrityError):
        DeterministicReplay(fixture_loader=lambda _ref: b"different").replay(manifest)

    tampered = manifest.to_dict()
    tampered["tool_results"] = {"call-1": {"result": "changed"}}
    with pytest.raises(ReplayIntegrityError):
        ReplayManifest.from_mapping(tampered)


def test_inspect_is_explicitly_display_only_and_never_execution_replay():
    manifest = DeterministicReplay.record(_trajectory())

    inspected = DeterministicReplay().run(ReplayMode.INSPECT, manifest=manifest)

    assert inspected.mode is ReplayMode.INSPECT
    assert inspected.display_only is True
    assert inspected.execution_replay is False
    assert inspected.to_dict()["execution_replay"] is False
