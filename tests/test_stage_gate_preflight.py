from __future__ import annotations

import hashlib

from scripts.ci import harness_stage_gate, spec_stage_gate


def test_domain_gates_do_not_own_spec_consistency_preflight():
    assert not hasattr(harness_stage_gate, "check_spec_consistency")
    assert not hasattr(spec_stage_gate, "check_spec_consistency")


def test_harness_acceptance_checks_recorded_artifact_hashes(tmp_path, monkeypatch):
    artifact = tmp_path / "report.json"
    artifact.write_text('{"passed": true}\n', encoding="utf-8")
    monkeypatch.setattr(harness_stage_gate, "ROOT", tmp_path)
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    item = {
        "id": "P4",
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


def test_stage_gate_report_creates_missing_parent(tmp_path):
    report_path = tmp_path / "artifacts" / "harness" / "stage-gates" / "p4-latest.json"
    payload = b'{"passed": true}\n'

    harness_stage_gate.persist_report(report_path, payload)

    assert report_path.read_bytes() == payload
