from __future__ import annotations

import hashlib
import json

from scripts.ci import ci_stage_gate


def test_snapshot_integrity_does_not_require_current_head(tmp_path, monkeypatch):
    snapshot_dir = tmp_path / "docs/specs/ci/evidence/snapshots/sample"
    snapshot_dir.mkdir(parents=True)
    baseline = {
        "schema_version": "ci-baseline/v2",
        "default_branch": {"name": "main", "sha": "a" * 40},
    }
    baseline_path = snapshot_dir / "phase0-baseline.json"
    baseline_path.write_text(json.dumps(baseline) + "\n", encoding="utf-8")
    manifest = {
        "evidence_kind": "frozen_snapshot",
        "snapshot_id": "sample",
        "spec_revision": "1.5",
        "created_at": "2026-10-30T00:00:00+00:00",
        "repository": "owner/repository",
        "target": {"name": "main", "ref": "main", "sha": "a" * 40},
        "sample_definition": {"pull_requests": "fixed sample"},
        "source_baseline_sha256": hashlib.sha256(baseline_path.read_bytes()).hexdigest(),
        "artifacts": {
            "phase0-baseline.json": {
                "sha256": hashlib.sha256(baseline_path.read_bytes()).hexdigest(),
                "bytes": baseline_path.stat().st_size,
            }
        },
    }
    (snapshot_dir / "manifest.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    monkeypatch.setattr(ci_stage_gate, "ROOT", tmp_path)

    result = ci_stage_gate.verify_snapshot("sample")

    assert result["status"] == "passed"
    assert result["target_sha"] == "a" * 40


def test_snapshot_integrity_rejects_changed_artifact(tmp_path, monkeypatch):
    snapshot_dir = tmp_path / "docs/specs/ci/evidence/snapshots/sample"
    snapshot_dir.mkdir(parents=True)
    baseline_path = snapshot_dir / "phase0-baseline.json"
    baseline_path.write_text('{"default_branch":{"sha":"' + "a" * 40 + '"}}\n', encoding="utf-8")
    (snapshot_dir / "manifest.json").write_text(json.dumps({
        "evidence_kind": "frozen_snapshot",
        "snapshot_id": "sample",
        "spec_revision": "1.5",
        "created_at": "2026-10-30T00:00:00+00:00",
        "repository": "owner/repository",
        "target": {"sha": "a" * 40},
        "sample_definition": {"pull_requests": "fixed sample"},
        "source_baseline_sha256": "b" * 64,
        "artifacts": {"phase0-baseline.json": {"sha256": "0" * 64, "bytes": 1}},
    }), encoding="utf-8")
    monkeypatch.setattr(ci_stage_gate, "ROOT", tmp_path)

    assert ci_stage_gate.verify_snapshot("sample")["status"] == "failed"


def test_snapshot_integrity_requires_provenance_metadata(tmp_path, monkeypatch):
    snapshot_dir = tmp_path / "docs/specs/ci/evidence/snapshots/sample"
    snapshot_dir.mkdir(parents=True)
    baseline_path = snapshot_dir / "phase0-baseline.json"
    baseline_path.write_text(json.dumps({"default_branch": {"sha": "a" * 40}}), encoding="utf-8")
    (snapshot_dir / "manifest.json").write_text(json.dumps({
        "evidence_kind": "frozen_snapshot",
        "snapshot_id": "sample",
        "target": {"name": "main", "sha": "a" * 40},
        "artifacts": {"phase0-baseline.json": {
            "sha256": hashlib.sha256(baseline_path.read_bytes()).hexdigest(),
            "bytes": baseline_path.stat().st_size,
        }},
    }), encoding="utf-8")
    monkeypatch.setattr(ci_stage_gate, "ROOT", tmp_path)

    result = ci_stage_gate.verify_snapshot("sample")

    assert result["status"] == "failed"
    assert "provenance metadata" in result["reason"]
