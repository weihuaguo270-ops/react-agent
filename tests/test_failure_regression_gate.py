"""P1: SoftwareTask / failure-regression gate contracts (delivery workflow removed)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from react_agent.eval.failure_regression_gate import (
    attach_software_task_gate,
    build_repair_feedback,
    evaluate_failure_regression_gate,
    evaluate_forced_reverify,
    gate_blocks_success,
    load_baseline_scan,
    run_gate_with_optional_repair,
    siblings_available,
)


def test_attach_software_task_gate_blocks_succeeded_on_hold(tmp_path):
    task_result = {
        "task_id": "fastapi-demo",
        "task_hash": "abc123def456",
        "status": "succeeded",
        "unauthorized_paths": [],
        "public_test": {"status": "passed"},
        "hidden_test": {"status": "passed"},
    }
    with patch(
        "react_agent.eval.failure_regression_gate.evaluate_failure_regression_gate",
        return_value={
            "available": True,
            "release_decision": "hold",
            "failure_gate_decision": "hold",
            "hard_failures": ["demo"],
        },
    ):
        enriched = attach_software_task_gate(
            task_result,
            out_dir=tmp_path / "gate",
            task_id="fastapi-demo",
            require_installed_siblings=False,
        )
    assert enriched["status"] == "failure_regression_hold"
    assert enriched["gate_blocked"] is True
    assert gate_blocks_success(enriched["failure_regression"]) is True


def test_gate_module_fail_closed_without_siblings(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "react_agent.eval.failure_regression_gate.siblings_available",
        lambda: (False, ["trace-debugger"]),
    )
    report = evaluate_failure_regression_gate(
        [{"episode_id": "x", "trajectory": {"session_id": "x", "steps": []}}],
        out_dir=tmp_path / "missing",
        require_installed_siblings=True,
    )
    assert report["available"] is False
    assert report["release_decision"] == "hold"
    assert gate_blocks_success(report) is True


@pytest.mark.skipif(not siblings_available()[0], reason="siblings not installed")
def test_gate_module_pass_with_siblings(tmp_path):
    episode = {
        "schema_version": "evaluation-episode/v1",
        "episode_id": "p1-pass-episode",
        "task": "P1 gate pass",
        "framework": "react-agent-software-task",
        "agent_version": "test",
        "split": "held_out",
        "acceptance_criteria": ["ok"],
        "expected_state": {"tests_passed": True, "unauthorized_paths_empty": True},
        "final_state": {"tests_passed": True, "unauthorized_paths_empty": True},
        "trajectory": {
            "session_id": "p1-pass-episode",
            "query": "P1 gate pass",
            "final_answer": "ok",
            "steps": [
                {
                    "step": 1,
                    "thought": "run",
                    "action": {"name": "public_test", "arguments": "{}"},
                    "observation": "passed",
                }
            ],
        },
    }
    report = evaluate_failure_regression_gate(
        [episode],
        out_dir=tmp_path / "p1-pass",
        require_installed_siblings=True,
    )
    assert report["available"] is True
    assert report["release_decision"] == "pass"
    assert report["failure_gate_decision"] == "pass"
    assert gate_blocks_success(report) is False


def test_forced_reverify_blocks_without_improvement(tmp_path):
    parent = tmp_path / "parent"
    parent.mkdir()
    (parent / "release.json").write_text(
        json.dumps({"decision": "hold", "hard_failures": ["x"]}), encoding="utf-8"
    )
    (parent / "failures.json").write_text(
        json.dumps({"decision": "hold"}), encoding="utf-8"
    )

    def fake_eval(episodes, **kwargs):
        out = Path(kwargs["out_dir"])
        out.mkdir(parents=True, exist_ok=True)
        report = {
            "available": True,
            "release_decision": "hold",
            "failure_gate_decision": "hold",
            "hard_failures": ["still bad"],
            "reverify": {
                "required": True,
                "improved_to_pass": False,
                "parent_run": str(parent),
                "parent_release_decision": "hold",
                "current_release_decision": "hold",
            },
        }
        (out / "pipeline_report.json").write_text(json.dumps(report), encoding="utf-8")
        (out / "release.json").write_text(
            json.dumps({"decision": "hold"}), encoding="utf-8"
        )
        return report

    with patch(
        "react_agent.eval.failure_regression_gate.evaluate_failure_regression_gate",
        fake_eval,
    ):
        report = evaluate_forced_reverify(
            [{"episode_id": "r", "trajectory": {"session_id": "r", "steps": []}}],
            out_dir=tmp_path / "child",
            parent_run_dir=parent,
            require_installed_siblings=False,
        )
    assert report["release_decision"] == "hold"
    assert report["reverify"]["improved_to_pass"] is False
    assert gate_blocks_success(report) is True
    assert "forced reverify" in " ".join(report["hard_failures"])


def test_forced_reverify_passes_when_improved(tmp_path):
    parent = tmp_path / "parent"
    parent.mkdir()
    (parent / "release.json").write_text(
        json.dumps({"decision": "hold"}), encoding="utf-8"
    )

    def fake_eval(episodes, **kwargs):
        out = Path(kwargs["out_dir"])
        out.mkdir(parents=True, exist_ok=True)
        report = {
            "available": True,
            "release_decision": "pass",
            "failure_gate_decision": "pass",
            "hard_failures": [],
            "reverify": {
                "required": True,
                "improved_to_pass": True,
                "parent_run": str(parent),
                "parent_release_decision": "hold",
                "current_release_decision": "pass",
            },
        }
        (out / "pipeline_report.json").write_text(json.dumps(report), encoding="utf-8")
        return report

    with patch(
        "react_agent.eval.failure_regression_gate.evaluate_failure_regression_gate",
        fake_eval,
    ):
        report = evaluate_forced_reverify(
            [{"episode_id": "r", "trajectory": {"session_id": "r", "steps": []}}],
            out_dir=tmp_path / "child",
            parent_run_dir=parent,
            require_installed_siblings=False,
        )
    assert report["release_decision"] == "pass"
    assert report["reverify"]["improved_to_pass"] is True
    assert gate_blocks_success(report) is False


def test_run_gate_with_optional_repair_then_reverify(tmp_path):
    calls = {"repair": 0}

    def fake_initial(episodes, **kwargs):
        out = Path(kwargs["out_dir"])
        out.mkdir(parents=True, exist_ok=True)
        (out / "release.json").write_text(
            json.dumps({"decision": "hold"}), encoding="utf-8"
        )
        (out / "failures.json").write_text(
            json.dumps({"decision": "hold"}), encoding="utf-8"
        )
        return {
            "available": True,
            "release_decision": "hold",
            "failure_gate_decision": "hold",
            "hard_failures": ["x"],
            "reverify": None,
        }

    def fake_reverify(episodes, **kwargs):
        assert kwargs.get("parent_run_dir") is not None
        return {
            "available": True,
            "release_decision": "pass",
            "failure_gate_decision": "pass",
            "hard_failures": [],
            "reverify": {
                "required": True,
                "improved_to_pass": True,
                "parent_release_decision": "hold",
                "current_release_decision": "pass",
            },
        }

    with patch(
        "react_agent.eval.failure_regression_gate.evaluate_failure_regression_gate",
        fake_initial,
    ), patch(
        "react_agent.eval.failure_regression_gate.evaluate_forced_reverify",
        fake_reverify,
    ):
        def repair_fn(hold):
            calls["repair"] += 1
            assert hold["release_decision"] == "hold"
            return {"status": "succeeded"}

        report = run_gate_with_optional_repair(
            [{"episode_id": "e", "trajectory": {"session_id": "e", "steps": []}}],
            out_dir=tmp_path / "orch",
            require_installed_siblings=False,
            repair_fn=repair_fn,
            rebuild_episodes_fn=lambda _r: [
                {"episode_id": "e2", "trajectory": {"session_id": "e2", "steps": []}}
            ],
        )
    assert calls["repair"] == 1
    assert report["phase"] == "reverify"
    assert report["reverify"]["improved_to_pass"] is True
    assert gate_blocks_success(report) is False


def test_build_repair_feedback_packages_findings_for_planner():
    feedback = build_repair_feedback(
        release_decision="hold",
        failure_gate_decision="hold",
        hard_failures=["business state mismatch"],
        review_reasons=["needs review"],
        findings={
            "gate_decision": "hold",
            "findings": [
                {
                    "id": "tool-timeout",
                    "dimension": "reliable-delivery",
                    "summary": "web_search timed out",
                    "severity": "high",
                }
            ],
        },
        failures={"triggered_rules": ["empty_final_answer"], "decision": "hold"},
        artifacts={"findings": "findings.json", "failures": "failures.json"},
    )
    assert feedback["schema_version"] == "repair-feedback/v1"
    assert feedback["actionable"] is True
    assert "trajectory_heuristics" in feedback["targets"]
    assert feedback["planner_safe"]["finding_summaries"] == ["web_search timed out"]
    assert feedback["planner_safe"]["triggered_rules"] == ["empty_final_answer"]
    assert feedback["planner_safe"]["hard_failures"] == ["business state mismatch"]


@pytest.mark.skipif(not siblings_available()[0], reason="siblings not installed")
def test_true_baseline_compare_pass_and_hold(tmp_path):
    ok_episode = {
        "schema_version": "evaluation-episode/v1",
        "episode_id": "baseline-ok",
        "task": "ok",
        "framework": "format_b",
        "agent_version": "test",
        "split": "held_out",
        "acceptance_criteria": ["ok"],
        "expected_state": {"tests_passed": True, "unauthorized_paths_empty": True},
        "final_state": {"tests_passed": True, "unauthorized_paths_empty": True},
        "trajectory": {
            "session_id": "baseline-ok",
            "query": "ok",
            "final_answer": "done",
            "steps": [
                {
                    "step": 1,
                    "thought": "run",
                    "action": {"name": "public_test", "arguments": "{}"},
                    "observation": "passed",
                }
            ],
        },
    }
    green_dir = tmp_path / "green"
    green = evaluate_failure_regression_gate(
        [ok_episode],
        out_dir=green_dir,
        require_installed_siblings=True,
    )
    assert green["release_decision"] == "pass"
    assert green["baseline_source"] == "self"
    baseline_path = Path(green["artifacts"]["current_scan"])
    loaded = load_baseline_scan(baseline_path)

    same = evaluate_failure_regression_gate(
        [ok_episode],
        out_dir=tmp_path / "same",
        require_installed_siblings=True,
        baseline_scan=loaded,
    )
    assert same["baseline_source"] == "provided"
    assert same["release_decision"] == "pass"
    assert same["failure_gate_decision"] == "pass"

    bad_episode = dict(ok_episode)
    bad_episode["episode_id"] = "baseline-bad"
    bad_episode["final_state"] = {
        "tests_passed": False,
        "unauthorized_paths_empty": True,
    }
    bad_episode["trajectory"] = {
        "session_id": "baseline-bad",
        "query": "ok",
        "final_answer": "",
        "steps": [
            {
                "step": 1,
                "thought": "run",
                "action": {"name": "public_test", "arguments": "{}"},
                "observation": "Error: ConnectionTimeout",
            }
        ],
    }
    red = evaluate_failure_regression_gate(
        [bad_episode],
        out_dir=tmp_path / "red",
        require_installed_siblings=True,
        baseline_scan=baseline_path,
    )
    assert red["baseline_source"] == "provided"
    assert red["release_decision"] == "hold"
    assert red["repair_feedback"]["actionable"] is True
    assert (tmp_path / "red" / "repair_feedback.json").is_file()
