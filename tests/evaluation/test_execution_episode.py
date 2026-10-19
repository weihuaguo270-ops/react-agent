from __future__ import annotations

from react_agent.eval.execution_scorer import run_execution_suite
from react_agent.harness.contracts import validate_trajectory


def test_execution_offline_result_contains_episode_and_fixture_evidence():
    report = run_execution_suite(
        modes=["offline_tools"],
        only_ids={"exec_calc_mul"},
    )

    assert report["fixture_manifest"]["data_sha256"]
    assert report["batch_id"].startswith("eval-batch-")
    result = report["results"][0]
    assert result["evaluation_episode"]["runner"] == "execution:offline_tools"
    assert result["evaluation_episode"]["artifacts"][0]["sha256"]
    assert validate_trajectory(result["trajectory"]) == []


def test_execution_agent_normalizes_legacy_trajectory_without_session_id():
    def mock_runner(question, timeout=90, max_steps=None, provider=None):
        return (
            "FINAL ANSWER: 143",
            {
                "final_answer": "143",
                "steps": [
                    {"step": 1, "action": {"name": "calculator"}, "observation": "143"}
                ],
            },
            0,
            0.1,
        )

    report = run_execution_suite(
        modes=["agent"],
        agent_runner=mock_runner,
        only_ids={"agent_calc_17x19"},
    )

    result = report["results"][0]
    assert result["trajectory"]["session_id"].startswith("execution:")
    assert result["evaluation_episode"]["fixture_manifest"]["data_sha256"]
    assert validate_trajectory(result["trajectory"]) == []
