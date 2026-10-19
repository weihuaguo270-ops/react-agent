"""Test that execution_scorer generates EvaluationEpisode instances.

P3 acceptance: execution_scorer must return EvaluationEpisode for each scored task.
"""
from __future__ import annotations

import pytest


def test_execution_scorer_generates_evaluation_episodes():
    """execution_scorer attaches EvaluationEpisode to each result."""
    from react_agent.eval.execution_scorer import run_execution_suite

    # Run with offline_tools mode (no LLM required)
    report = run_execution_suite(modes=["offline_tools"], only_ids={"exec_calc_mul"})

    assert "evaluation_episodes" in report, "P3: report must include evaluation_episodes field"
    episodes = report["evaluation_episodes"]
    assert isinstance(episodes, list), "evaluation_episodes must be a list"

    # At least one episode should be generated for the scored task
    assert len(episodes) > 0, "should generate at least one episode for non-skipped tasks"

    # Validate episode structure
    first_episode = episodes[0]
    assert "schema_version" in first_episode, "episode must have schema_version"
    assert first_episode["schema_version"] == "evaluation-episode/v1"
    assert "episode_id" in first_episode, "episode must have episode_id"
    assert "query" in first_episode, "episode must have query"
    assert "runner" in first_episode, "episode must have runner"
    assert first_episode["runner"].startswith("execution:"), "runner should indicate execution mode"
    assert "batch_id" in first_episode, "episode must have batch_id"
    assert "trajectory" in first_episode, "episode must have trajectory"
    assert "score" in first_episode, "episode must have score"
    assert "fixture_manifest" in first_episode, "episode must have fixture_manifest"

    # Validate trajectory structure
    trajectory = first_episode["trajectory"]
    assert "session_id" in trajectory, "trajectory must have session_id"
    assert "schema_version" in trajectory, "trajectory must have schema_version"
    assert trajectory["schema_version"] == "1" or "harness-trajectory" in str(trajectory.get("schema_version", ""))

    # Validate fixture manifest
    manifest = first_episode["fixture_manifest"]
    assert "schema_version" in manifest, "manifest must have schema_version"
    assert manifest["schema_version"] == "fixture-manifest/v1"
    assert "fixture_id" in manifest, "manifest must have fixture_id"
    assert "data_sha256" in manifest, "manifest must have data_sha256"

    # Validate score structure
    score = first_episode["score"]
    assert "passed" in score, "score must have passed field"
    assert isinstance(score["passed"], bool), "passed must be boolean"


def test_execution_episode_can_be_deserialized():
    """EvaluationEpisode from execution_scorer can round-trip through from_mapping."""
    from react_agent.eval.execution_scorer import run_execution_suite
    from react_agent.harness import EvaluationEpisode

    report = run_execution_suite(modes=["offline_tools"], only_ids={"exec_calc_mul"})
    episodes = report["evaluation_episodes"]
    assert len(episodes) > 0

    # Deserialize and validate
    episode_dict = episodes[0]
    episode = EvaluationEpisode.from_mapping(episode_dict)

    assert episode.episode_id
    assert episode.query
    assert episode.runner.startswith("execution:")
    assert episode.batch_id
    assert episode.fixture_manifest is not None
    assert episode.fixture_manifest.fixture_id
    assert episode.fixture_manifest.data_sha256
    assert isinstance(episode.trajectory, dict)
    assert isinstance(episode.score, dict)


def test_execution_episode_preserved_in_legacy_results():
    """Episode is attached to individual results for backward compatibility."""
    from react_agent.eval.execution_scorer import run_execution_suite

    report = run_execution_suite(modes=["offline_tools"], only_ids={"exec_calc_mul"})
    results = report["results"]

    # Find a non-skipped result
    scored = [r for r in results if not r.get("skipped")]
    assert len(scored) > 0, "should have at least one scored result"

    first_result = scored[0]
    assert "evaluation_episode" in first_result, "legacy result should preserve episode"
    assert "trajectory" in first_result, "legacy result should preserve trajectory"

    # Episode in result should match episode in report's episode list
    result_episode = first_result["evaluation_episode"]
    report_episodes = report["evaluation_episodes"]

    # Should find matching episode by episode_id
    matching = [ep for ep in report_episodes if ep["episode_id"] == result_episode["episode_id"]]
    assert len(matching) == 1, "episode should appear exactly once in report episode list"


def test_execution_suite_fixture_manifest_consistency():
    """All episodes in a batch share the same fixture manifest."""
    from react_agent.eval.execution_scorer import run_execution_suite

    report = run_execution_suite(modes=["offline_tools"])

    episodes = report["evaluation_episodes"]
    if len(episodes) < 2:
        pytest.skip("need at least 2 episodes to test fixture consistency")

    # All episodes should reference the same fixture
    manifests = [ep["fixture_manifest"] for ep in episodes]
    first_sha = manifests[0]["data_sha256"]

    for manifest in manifests[1:]:
        assert manifest["data_sha256"] == first_sha, "all episodes in batch should share fixture SHA256"

    # Report-level fixture manifest should match episode manifests
    report_manifest = report["fixture_manifest"]
    assert report_manifest["data_sha256"] == first_sha
