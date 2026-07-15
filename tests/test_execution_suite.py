"""Execution suite offline 测试"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from react_agent.eval.execution_scorer import (
    load_execution_dataset,
    run_execution_suite,
    score_task,
)


def test_dataset_loads():
    tasks = load_execution_dataset()
    assert len(tasks) >= 6
    assert all("id" in t and "steps" in t for t in tasks)


def test_suite_full_pass():
    report = run_execution_suite()
    s = report["summary"]
    assert s["total"] == len(report["results"])
    assert s["passed"] == s["total"], report
    assert s["pass_rate"] == 100.0


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
