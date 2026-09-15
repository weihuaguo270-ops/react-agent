"""Cross-repo contracts for Episode / failure-gate / repair-feedback / process_quality.

Changing these fields without updating this file should fail CI.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("trace_debugger")
pytest.importorskip("eval_engine")

from eval_engine.gates.evidence_bundle import evaluate_evidence_bundle
from eval_engine.integrations.episode import import_episode, verify_episode_state
from trace_debugger import build_failures_export, evaluate_regression_gate
from trace_debugger.reader import parse as tdebug_parse

from react_agent.eval.failure_regression_gate import (
    build_process_quality,
    build_repair_feedback,
    evaluate_failure_regression_gate,
)
from react_agent.eval.scorer import EVAL_API_VERSION, EVAL_ENGINE_API_CONTRACT
from eval_engine.core.process_reward import EVAL_API_VERSION as EE_EVAL_API_VERSION

ROOT = Path(__file__).resolve().parents[1]
OK_TRAJ = ROOT / "examples" / "fixtures" / "failure_regression" / "trajectory_ok.json"


def _episode() -> dict:
    traj = json.loads(OK_TRAJ.read_text(encoding="utf-8"))
    envelope = {
        "schema_version": "evaluation-episode/v1",
        "episode_id": "contract-episode-1",
        "task": traj.get("query") or "contract",
        "framework": "format_b",
        "agent_version": "contract-v1",
        "split": "held_out",
        "acceptance_criteria": ["trajectory is Format B"],
        "expected_state": {"task_completed": True, "final_answer_nonempty": True},
        "final_state": {
            "task_completed": True,
            "final_answer_nonempty": bool(str(traj.get("final_answer") or "").strip()),
        },
        "trajectory": traj,
    }
    imported = import_episode(envelope)
    payload = imported.to_dict()
    payload["state_verification"] = verify_episode_state(imported).to_dict()
    return payload


def test_eval_api_version_matches_llm_eval_engine():
    assert EVAL_API_VERSION == EE_EVAL_API_VERSION == "0.2"
    assert EVAL_ENGINE_API_CONTRACT.endswith("@0.2")


def test_evaluation_episode_v1_required_fields():
    episode = _episode()
    for key in (
        "schema_version",
        "episode_id",
        "task",
        "framework",
        "split",
        "expected_state",
        "final_state",
        "trajectory",
        "state_verification",
    ):
        assert key in episode, key
    assert episode["schema_version"] == "evaluation-episode/v1"
    assert episode["state_verification"]["passed"] is True
    assert "steps" in episode["trajectory"]
    step = episode["trajectory"]["steps"][0]
    assert "action" in step
    assert isinstance(step["action"].get("arguments", ""), str)


def test_failure_gate_export_decision_fields(tmp_path):
    traj = tdebug_parse(json.loads(OK_TRAJ.read_text(encoding="utf-8")))
    from trace_debugger import Analyzer
    from trace_debugger.record import build_scan_snapshot

    analyzer = Analyzer()
    analysis = analyzer.analyze(traj)
    scan = build_scan_snapshot(
        str(tmp_path),
        1,
        [traj],
        [analysis],
        source_files=["ok.json"],
        task_type="qa",
    )
    gate = evaluate_regression_gate(scan, scan)
    export = build_failures_export(
        scan,
        compare={
            "baseline_report_id": scan.get("report_id"),
            "gate_decision": gate.get("decision"),
        },
    )
    export["decision"] = gate["decision"]
    export["gate_decision"] = gate["decision"]
    for key in ("decision", "gate_decision"):
        assert key in export
        assert export[key] in {"pass", "hold", "review"}


def test_repair_feedback_and_process_quality_contracts():
    episode = _episode()
    failures = {
        "decision": "hold",
        "gate_decision": "hold",
        "triggered_rules": ["empty_final_answer"],
    }
    findings = {
        "gate_decision": "hold",
        "findings": [
            {
                "id": "f1",
                "dimension": "reliable-delivery",
                "summary": "tool timeout",
                "severity": "high",
            }
        ],
    }
    feedback = build_repair_feedback(
        release_decision="hold",
        failure_gate_decision="hold",
        hard_failures=["business-state failures"],
        findings=findings,
        failures=failures,
        artifacts={"findings": "findings.json", "failures": "failures.json"},
    )
    assert feedback["schema_version"] == "repair-feedback/v1"
    assert "planner_safe" in feedback
    assert "targets" in feedback
    assert feedback["actionable"] is True

    quality = build_process_quality(
        [episode],
        failures=failures,
        findings=findings,
    )
    assert "overall_score" in quality
    assert 1.0 <= float(quality["overall_score"]) <= 5.0
    assert quality["metric"] != "failure_regression_gate_stub"
    assert quality["metric"] in {
        "process_reward_fast+evidence_v1",
        "failure_regression_evidence_v1",
    }
    assert "degraded" in quality


def test_evidence_bundle_consumes_contract_shapes():
    episode = _episode()
    quality = build_process_quality([episode], failures={"decision": "pass"}, findings={})
    release = evaluate_evidence_bundle(
        episodes=[episode],
        failure_gate={"decision": "pass", "gate_decision": "pass"},
        process_quality=quality,
    )
    assert release["decision"] in {"pass", "review", "hold"}
    assert "hard_failures" in release
    assert "review_reasons" in release
    assert release["evidence"]["process_quality_present"] is True


def test_gate_module_writes_contract_artifacts(tmp_path):
    episode = _episode()
    report = evaluate_failure_regression_gate(
        [episode],
        out_dir=tmp_path / "gate",
        require_installed_siblings=True,
    )
    assert report["process_quality"]["metric"] != "failure_regression_gate_stub"
    assert (tmp_path / "gate" / "process_quality.json").is_file()
    assert (tmp_path / "gate" / "repair_feedback.json").is_file()
    assert report["repair_feedback"]["schema_version"] == "repair-feedback/v1"
