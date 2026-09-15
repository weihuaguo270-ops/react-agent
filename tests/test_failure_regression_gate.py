"""P1: SoftwareTask / GitHub Delivery default-wire the failure-regression gate."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from react_agent.apps.github_delivery import (
    DeliveryTask,
    GitHubDeliveryWorkflow,
    Replacement,
    WorkflowConfig,
)
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


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _repository(tmp_path: Path) -> Path:
    repo = tmp_path / "service"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "test")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "service.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "test_service.py").write_text(
        "from service import VALUE\n\ndef test_value():\n    assert VALUE == 2\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture")
    return repo


def _task(repo: Path) -> DeliveryTask:
    return DeliveryTask(
        task_id="issue-gate-1",
        repository=str(repo),
        issue_url="local://issues/gate-1",
        split="held_out",
        replacements=(Replacement("service.py", "VALUE = 1", "VALUE = 2"),),
        test_command=("python", "-m", "pytest", "-q"),
        acceptance_criteria=("tests pass", "base branch remains unchanged"),
    )


def test_workflow_config_enables_gate_by_default():
    config = WorkflowConfig(Path("artifacts"))
    assert config.failure_regression_gate is True
    assert config.failure_regression_require_siblings is True


def test_delivery_fail_closed_when_siblings_missing(tmp_path, monkeypatch):
    repo = _repository(tmp_path)
    monkeypatch.setattr(
        "react_agent.eval.failure_regression_gate.siblings_available",
        lambda: (False, ["trace-debugger", "llm-eval-engine"]),
    )
    workflow = GitHubDeliveryWorkflow(
        WorkflowConfig(tmp_path / "artifacts", failure_regression_gate=True)
    )
    report = workflow.run(_task(repo), idempotency_key="gate-missing")
    assert report["status"] == "failure_regression_unavailable"
    assert report["passed"] is False
    assert report["failure_regression"]["available"] is False
    assert report["failure_regression"]["release_decision"] == "hold"
    codes = {item["code"] for item in report["alerts"]}
    assert "failure_regression_unavailable" in codes


def test_delivery_holds_when_gate_returns_hold(tmp_path, monkeypatch):
    repo = _repository(tmp_path)

    def fake_gate(*_args, **_kwargs):
        return {
            "schema_version": "failure-regression-gate/v1",
            "available": True,
            "release_decision": "hold",
            "failure_gate_decision": "hold",
            "hard_failures": ["injected hold"],
            "review_reasons": [],
        }

    monkeypatch.setattr(
        "react_agent.eval.failure_regression_gate.evaluate_failure_regression_gate",
        fake_gate,
    )
    workflow = GitHubDeliveryWorkflow(
        WorkflowConfig(tmp_path / "artifacts", failure_regression_gate=True)
    )
    report = workflow.run(_task(repo), idempotency_key="gate-hold")
    assert report["status"] == "failure_regression_hold"
    assert report["passed"] is False
    assert report["test_result"]["passed"] is True
    assert report["failure_regression"]["release_decision"] == "hold"


def test_delivery_passes_when_gate_passes(tmp_path, monkeypatch):
    repo = _repository(tmp_path)

    def fake_gate(episodes, **kwargs):
        out = Path(kwargs["out_dir"])
        out.mkdir(parents=True, exist_ok=True)
        report = {
            "schema_version": "failure-regression-gate/v1",
            "available": True,
            "release_decision": "pass",
            "failure_gate_decision": "pass",
            "hard_failures": [],
            "review_reasons": [],
            "artifacts": {"release": str(out / "release.json")},
        }
        (out / "pipeline_report.json").write_text(
            json.dumps(report), encoding="utf-8"
        )
        return report

    monkeypatch.setattr(
        "react_agent.eval.failure_regression_gate.evaluate_failure_regression_gate",
        fake_gate,
    )
    workflow = GitHubDeliveryWorkflow(
        WorkflowConfig(tmp_path / "artifacts", failure_regression_gate=True)
    )
    report = workflow.run(_task(repo), idempotency_key="gate-pass")
    assert report["status"] == "shadow_passed"
    assert report["passed"] is True
    assert report["failure_regression"]["release_decision"] == "pass"
    assert any(step["action"]["name"] == "failure_regression_gate" for step in report["episode"]["trajectory"]["steps"])


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


def test_hold_marks_reverify_required(tmp_path, monkeypatch):
    repo = _repository(tmp_path)

    def fake_gate(*_a, **_k):
        return {
            "schema_version": "failure-regression-gate/v1",
            "available": True,
            "release_decision": "hold",
            "failure_gate_decision": "hold",
            "hard_failures": ["hold"],
            "review_reasons": [],
        }

    monkeypatch.setattr(
        "react_agent.eval.failure_regression_gate.evaluate_failure_regression_gate",
        fake_gate,
    )
    # Bypass mark path inside delivery by using real mark via unpatched helper:
    # Delivery calls evaluate then mark_reverify_required from the live module.
    workflow = GitHubDeliveryWorkflow(
        WorkflowConfig(tmp_path / "artifacts", failure_regression_gate=True)
    )
    report = workflow.run(_task(repo), idempotency_key="hold-reverify-mark")
    assert report["status"] == "failure_regression_hold"
    reverify = report["failure_regression"]["reverify"]
    assert reverify["required"] is True
    assert reverify["improved_to_pass"] is False
    assert "reverify_from" in reverify["blocked"] or "parent_run" in reverify


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


def test_delivery_reverify_from_parent_hold(tmp_path, monkeypatch):
    repo = _repository(tmp_path)
    parent = tmp_path / "parent-hold"
    parent.mkdir()
    (parent / "release.json").write_text(
        json.dumps({"decision": "hold"}), encoding="utf-8"
    )

    def fake_forced(episodes, **kwargs):
        assert Path(kwargs["parent_run_dir"]) == parent.resolve()
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

    monkeypatch.setattr(
        "react_agent.eval.failure_regression_gate.evaluate_forced_reverify",
        fake_forced,
    )
    workflow = GitHubDeliveryWorkflow(
        WorkflowConfig(tmp_path / "artifacts", failure_regression_gate=True)
    )
    report = workflow.run(
        _task(repo),
        idempotency_key="reverify-ok",
        reverify_from=parent,
    )
    assert report["status"] == "shadow_passed"
    assert report["failure_regression"]["reverify"]["improved_to_pass"] is True


def test_delivery_repair_loop_on_test_failure(tmp_path, monkeypatch):
    repo = _repository(tmp_path)
    # Bad replacement that fails tests initially — RepairLoop will fix VALUE.
    task = DeliveryTask(
        task_id="issue-repair-1",
        repository=str(repo),
        issue_url="local://issues/repair-1",
        split="held_out",
        replacements=(Replacement("service.py", "VALUE = 1", "VALUE = 9"),),
        test_command=("python", "-m", "pytest", "-q"),
        acceptance_criteria=("tests pass",),
        allowed_paths=("service.py",),
    )

    class Loop:
        planner = staticmethod(
            lambda _ctx: {
                "replacements": [
                    {"path": "service.py", "old": "VALUE = 1", "new": "VALUE = 2"}
                ]
            }
        )
        executor = object()  # replaced by delivery binding
        config = None
        observer = None

    monkeypatch.setattr(
        "react_agent.eval.failure_regression_gate.evaluate_failure_regression_gate",
        lambda *a, **k: {
            "available": True,
            "release_decision": "pass",
            "failure_gate_decision": "pass",
            "hard_failures": [],
            "reverify": None,
        },
    )
    workflow = GitHubDeliveryWorkflow(
        WorkflowConfig(
            tmp_path / "artifacts",
            failure_regression_gate=True,
            repair_loop=Loop(),
            failure_regression_auto_repair=True,
        )
    )
    report = workflow.run(task, idempotency_key="repair-then-pass")
    assert report["status"] == "shadow_passed"
    assert report["repair"]["status"] == "succeeded"
    assert report["test_result"]["passed"] is True


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


def test_delivery_repair_receives_repair_feedback(tmp_path, monkeypatch):
    repo = _repository(tmp_path)
    seen = {}

    class Loop:
        @staticmethod
        def planner(ctx):
            seen["repair_feedback"] = ctx.get("repair_feedback")
            return {
                "replacements": [
                    {"path": "service.py", "old": "VALUE = 1", "new": "VALUE = 2"}
                ]
            }

        executor = object()
        config = None
        observer = None

    monkeypatch.setattr(
        "react_agent.eval.failure_regression_gate.evaluate_failure_regression_gate",
        lambda *a, **k: {
            "available": True,
            "release_decision": "hold",
            "failure_gate_decision": "hold",
            "hard_failures": ["gate hold"],
            "repair_feedback": {
                "schema_version": "repair-feedback/v1",
                "planner_safe": {
                    "hard_failures": ["gate hold"],
                    "finding_summaries": ["timeout"],
                    "targets": ["trajectory_heuristics"],
                },
            },
            "reverify": None,
        },
    )
    monkeypatch.setattr(
        "react_agent.eval.failure_regression_gate.evaluate_forced_reverify",
        lambda *a, **k: {
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
        },
    )
    # First gate hold with tests already passing triggers repair_loop_after_hold.
    task = _task(repo)
    workflow = GitHubDeliveryWorkflow(
        WorkflowConfig(
            tmp_path / "artifacts",
            failure_regression_gate=True,
            repair_loop=Loop(),
            failure_regression_auto_repair=True,
        )
    )
    report = workflow.run(task, idempotency_key="feedback-to-repair")
    assert seen["repair_feedback"]["hard_failures"] == ["gate hold"]
    assert report["status"] == "shadow_passed"


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
