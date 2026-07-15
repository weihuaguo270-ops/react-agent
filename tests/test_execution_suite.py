"""Execution suite：offline + agent(mock) 测试"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from react_agent.eval.execution_scorer import (
    load_execution_dataset,
    run_execution_suite,
    score_task,
)


def test_dataset_has_both_modes_and_difficulties():
    tasks = load_execution_dataset()
    modes = {t.get("mode", "offline_tools") for t in tasks}
    assert "offline_tools" in modes
    assert "agent" in modes
    agent = [t for t in tasks if t.get("mode") == "agent"]
    assert len(agent) >= 20
    diffs = {t.get("difficulty") for t in agent}
    assert {"easy", "medium", "hard"} <= diffs


def test_suite_offline_full_pass():
    report = run_execution_suite(modes=["offline_tools"])
    s = report["summary"]
    assert s["total"] >= 10
    assert s["passed"] == s["total"], report
    assert s["pass_rate"] == 100.0
    assert "by_difficulty" in report


def test_failing_expectation():
    task = {
        "id": "bad",
        "mode": "offline_tools",
        "tags": ["execution"],
        "steps": [
            {
                "tool": "calculator",
                "arguments": {"expression": "1 + 1"},
                "expect_equals": "999",
            }
        ],
    }
    r = score_task(task)
    assert r["passed"] is False


def test_agent_require_all_and_forbid_with_mock():
    def mock_runner(question, timeout=90, max_steps=None, provider=None):
        traj = {
            "final_answer": "143",
            "steps": [
                {"step": 1, "action": {"name": "calculator"}, "observation": "143"},
                {"step": 2, "action": {"name": "execute_python"}, "observation": "143"},
            ],
        }
        stdout = "[调工具] calculator({})\n[调工具] execute_python({})\nFINAL ANSWER: 143"
        return stdout, traj, 0, 0.1

    report = run_execution_suite(
        modes=["agent"],
        agent_runner=mock_runner,
        only_ids={"agent_dual_verify_143"},
    )
    assert report["summary"]["passed"] == 1

    def bad_runner(question, timeout=90, max_steps=None, provider=None):
        traj = {
            "final_answer": "100",
            "steps": [
                {"step": 1, "action": {"name": "web_search"}, "observation": "x"},
                {"step": 2, "action": {"name": "calculator"}, "observation": "100"},
            ],
        }
        stdout = "[调工具] web_search({})\n[调工具] calculator({})\nFINAL ANSWER: 100"
        return stdout, traj, 0, 0.1

    report2 = run_execution_suite(
        modes=["agent"],
        agent_runner=bad_runner,
        only_ids={"agent_tool_choice_no_rag"},
    )
    assert report2["summary"]["passed"] == 0
