"""Reliability harness smoke test"""
import os
from react_agent.harness.contracts import validate_trajectory

os.environ["REACT_AGENT_SKIP_RAG"] = "1"

from tests._load_eval_script import load_eval_script  # noqa: E402


def test_reliability_harness_all_pass():
    run_harness = load_eval_script("run_reliability_harness").run_harness
    report = run_harness()
    assert report["summary"]["total"] == 4
    assert report["summary"]["passed"] == 4, report
    assert report["fixture_manifest"]["data_sha256"]
    assert report["batch_id"].startswith("eval-batch-")
    episode = report["scenarios"][0]["evaluation_episode"]
    assert episode["schema_version"] == "evaluation-episode/v1"
    assert episode["artifacts"][0]["sha256"]
    assert validate_trajectory(episode["trajectory"]) == []

