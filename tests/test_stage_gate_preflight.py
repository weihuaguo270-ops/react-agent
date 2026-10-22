from __future__ import annotations

import hashlib

from scripts.ci import harness_stage_gate, spec_stage_gate


def test_harness_gate_stops_before_progress_read_when_consistency_fails(monkeypatch):
    monkeypatch.setattr(harness_stage_gate, "check_spec_consistency", lambda: False)
    monkeypatch.setattr(harness_stage_gate, "load_progress", lambda: (_ for _ in ()).throw(AssertionError("progress read")))
    monkeypatch.setattr("sys.argv", ["harness_stage_gate.py", "--stage", "P4"])

    assert harness_stage_gate.main() == 2


def test_spec_gate_stops_before_registry_read_when_consistency_fails(monkeypatch):
    monkeypatch.setattr(spec_stage_gate, "check_spec_consistency", lambda _spec: False)
    monkeypatch.setattr(spec_stage_gate, "load_config", lambda _spec: (_ for _ in ()).throw(AssertionError("registry read")))
    monkeypatch.setattr("sys.argv", ["spec_stage_gate.py", "--spec", "work", "--stage", "P1"])

    assert spec_stage_gate.main() == 2


def test_harness_acceptance_checks_recorded_artifact_hashes(tmp_path, monkeypatch):
    artifact = tmp_path / "report.json"
    artifact.write_text('{"passed": true}\n', encoding="utf-8")
    monkeypatch.setattr(harness_stage_gate, "ROOT", tmp_path)
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    item = {
        "id": "P4-1",
        "status": "complete",
        "evidence": ["report.json"],
        "artifacts": [{"path": "report.json", "sha256": digest}],
    }

    result = harness_stage_gate.check_acceptance_evidence([item])[0]
    assert result["passed"] is True
    assert result["artifact_hashes"][0]["actual"] == digest

    item["artifacts"][0]["sha256"] = "0" * 64
    result = harness_stage_gate.check_acceptance_evidence([item])[0]
    assert result["passed"] is False


def test_passed_gate_preserves_partial_spec_phase():
    assert harness_stage_gate.stage_status_after_gate(True, "partial") == "in_progress"
    assert harness_stage_gate.stage_status_after_gate(True, "complete") == "complete"
