from __future__ import annotations

import json

import pytest

from scripts.ci import refresh_phase0_baseline as collector


def test_required_jobs_follow_observed_protection_including_matrix_names():
    jobs = {item["job"]: item for item in collector.workflow_responsibilities(
        ["lint", "test (3.10)", "test (3.11)", "Harness P4 stage gate"]
    )}
    assert jobs["PR ready audit"]["required_now"] is False
    assert jobs["test"]["required_contexts"] == ["test (3.10)", "test (3.11)"]
    assert jobs["test-windows"]["required_now"] is False
    assert jobs["Harness P4 stage gate"]["required_now"] is True
    assert jobs["Evaluation evidence"]["required_now"] is False
    assert not any(item["required_now"] for item in collector.workflow_responsibilities([]))


def test_observation_render_keeps_later_phase_work_out_of_phase0_exit():
    # Historical sample used only as offline rendering input, not fresh evidence.
    report = json.loads((collector.EVIDENCE / "phase0-baseline.json").read_text(encoding="utf-8"))
    report["evidence_kind"] = "current_observation"
    text = collector.render_markdown(report)
    assert text.startswith("# CI 当前观测报告")
    assert "不要求 Phase 1 语义校验、R9 远端执行或 Phase 2 shadow 窗口先完成" in text
    assert "仍待完成：独立复审逐样本证据、Phase 1" not in text
    assert "合并提交关联 runs（按实际事件保留）" in text
    assert "阶段状态：" not in text


def test_snapshot_id_collision_is_rejected_before_collection(tmp_path, monkeypatch):
    monkeypatch.setattr(collector, "EVIDENCE", tmp_path)
    monkeypatch.setattr("sys.argv", ["collector", "--mode", "snapshot", "--snapshot-id", "frozen"])
    snapshot = tmp_path / "snapshots/frozen"
    snapshot.mkdir(parents=True)
    sentinel = snapshot / "manifest.json"
    sentinel.write_text("original evidence", encoding="utf-8")

    def unexpected_network(_endpoint):
        pytest.fail("an existing snapshot must be rejected before network collection")

    monkeypatch.setattr(collector, "gh_json", unexpected_network)
    with pytest.raises(SystemExit) as result:
        collector.main()
    assert result.value.code == 2
    assert sentinel.read_text(encoding="utf-8") == "original evidence"


def test_cancelled_run_keeps_classification_and_reproduction_evidence(monkeypatch):
    monkeypatch.setattr(collector, "gh_json", lambda _endpoint: {
        "jobs": [{"name": "lint", "conclusion": "cancelled", "steps": [
            {"name": "Ruff", "conclusion": "cancelled"},
        ]}],
    })
    jobs = collector.reviewed_jobs({"id": 42, "conclusion": "cancelled"})
    assert jobs[0]["conclusion"] == "cancelled"
    step = jobs[0]["failed_steps"][0]
    assert step["category"] == "lint"
    assert "heuristic" in step["classification_basis"]
    assert step["reproduction_command"] == "ruff check src/ tests/"


def test_manifest_artifacts_exclude_manifest_self_hash(tmp_path):
    baseline = tmp_path / "phase0-baseline.json"
    baseline.write_text('{"ok": true}\n', encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text("placeholder\n", encoding="utf-8")

    artifacts = collector.manifest_artifacts(tmp_path)

    assert set(artifacts) == {"phase0-baseline.json"}
    assert artifacts["phase0-baseline.json"]["sha256"] == collector.sha256_file(baseline)


def test_manifest_target_matches_snapshot_gate_contract():
    assert collector.manifest_target("main", "a" * 40) == {
        "name": "main",
        "sha": "a" * 40,
    }
