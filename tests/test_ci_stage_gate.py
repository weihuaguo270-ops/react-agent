from __future__ import annotations

import hashlib
import json

from scripts.ci import audit_workflow_security, ci_stage_gate


def test_test_environment_exposes_repository_source_and_permissive_dirs(monkeypatch, tmp_path):
    monkeypatch.setattr(ci_stage_gate, "ROOT", tmp_path)
    monkeypatch.setenv("PYTHONPATH", "existing-path")

    env = ci_stage_gate.test_environment()

    assert env["REACT_AGENT_PERMISSIVE_TEST_DIRS"] == "1"
    assert env["PYTHONPATH"].split(ci_stage_gate.os.pathsep) == [str((tmp_path / "src").resolve()), "existing-path"]


def test_snapshot_integrity_does_not_require_current_head(tmp_path, monkeypatch):
    snapshot_dir = tmp_path / "docs/specs/ci/evidence/snapshots/sample"
    snapshot_dir.mkdir(parents=True)
    baseline = {
        "schema_version": "ci-baseline/v2",
        "default_branch": {"name": "main", "sha": "a" * 40},
    }
    baseline_path = snapshot_dir / "phase0-baseline.json"
    baseline_path.write_text(json.dumps(baseline) + "\n", encoding="utf-8")
    canonical = baseline_path.read_bytes().replace(b"\r\n", b"\n")
    manifest = {
        "evidence_kind": "frozen_snapshot",
        "snapshot_id": "sample",
        "spec_revision": "1.5",
        "created_at": "2026-10-30T00:00:00+00:00",
        "repository": "owner/repository",
        "target": {"name": "main", "ref": "main", "sha": "a" * 40},
        "sample_definition": {"pull_requests": "fixed sample"},
        "source_baseline_sha256": hashlib.sha256(canonical).hexdigest(),
        "artifacts": {
            "phase0-baseline.json": {
                "sha256": hashlib.sha256(canonical).hexdigest(),
                "bytes": len(canonical),
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


def test_snapshot_integrity_normalizes_windows_newlines(tmp_path, monkeypatch):
    snapshot_dir = tmp_path / "docs/specs/ci/evidence/snapshots/sample"
    snapshot_dir.mkdir(parents=True)
    baseline_path = snapshot_dir / "phase0-baseline.json"
    baseline_path.write_bytes(b'{\r\n  "default_branch": {"sha": "' + b"a" * 40 + b'"}\r\n}\r\n')
    canonical = baseline_path.read_bytes().replace(b"\r\n", b"\n")
    manifest = {
        "evidence_kind": "frozen_snapshot",
        "snapshot_id": "sample",
        "spec_revision": "1.5",
        "created_at": "2026-10-30T00:00:00+00:00",
        "repository": "owner/repository",
        "target": {"name": "main", "sha": "a" * 40},
        "sample_definition": {"pull_requests": "fixed sample"},
        "source_baseline_sha256": hashlib.sha256(canonical).hexdigest(),
        "artifacts": {"phase0-baseline.json": {
            "sha256": hashlib.sha256(canonical).hexdigest(),
            "bytes": len(canonical),
        }},
    }
    (snapshot_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(ci_stage_gate, "ROOT", tmp_path)

    assert ci_stage_gate.verify_snapshot("sample")["status"] == "passed"


def test_phase1_backtest_evidence_can_pass_while_subset_eligibility_is_blocked(tmp_path, monkeypatch):
    """Unmapped paths block subset gating, not an otherwise valid replay record."""
    sample_path = tmp_path / "sample.json"
    sample_path.write_text("{}", encoding="utf-8")
    sample = {"source_sha": "a" * 40}
    registry_path = tmp_path / "docs/specs/ci/registry-v2.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(ci_stage_gate, "ROOT", tmp_path)
    backtest = {
        "schema_version": "ci-selector-backtest/v2",
        "sample_id": "sample",
        "spec_revision": "1.5",
        "source_sha": sample["source_sha"],
        "source_sha256": hashlib.sha256(sample_path.read_bytes()).hexdigest(),
        "sample_size": 100,
        "samples": [{"changed_files": 4, "unmapped_paths": ["path"]}] + [
            {"changed_files": 0, "unmapped_paths": []} for _ in range(99)
        ],
        "registry_validation": {"status": "pass"},
        "metrics": {
            "changed_files": 4,
            "mapped_files": 3,
            "unmapped_files": 1,
            "mapped_coverage": 0.75,
            "false_positive_rules": None,
            "missed_expected_rules": None,
        },
        "conclusion": "blocked",
        "registry_sha256": hashlib.sha256(registry_path.read_bytes()).hexdigest(),
    }

    assert ci_stage_gate.validate_selector_backtest(backtest, sample, "sample", sample_path, "1.5")

    backtest["metrics"]["mapped_files"] = 2
    assert not ci_stage_gate.validate_selector_backtest(backtest, sample, "sample", sample_path, "1.5")

    backtest["metrics"] = None
    assert not ci_stage_gate.validate_selector_backtest(backtest, sample, "sample", sample_path, "1.5")


def test_gate_report_hash_matches_persisted_report_bytes(tmp_path, monkeypatch):
    report = tmp_path / "report.json"
    report.write_text('{"ok": true}\n', encoding="utf-8", newline="\r\n")
    assert hashlib.sha256(ci_stage_gate.canonical_bytes(report)).hexdigest() == hashlib.sha256(
        report.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    ).hexdigest()


def test_workflow_security_audit_accepts_digest_pinned_repo_local_base(tmp_path, monkeypatch):
    dockerfile = tmp_path / "eval/Dockerfile"
    dockerfile.parent.mkdir()
    dockerfile.write_text("FROM react-agent-sandbox:0.7.0\n", encoding="utf-8")
    sandbox = tmp_path / "Dockerfile.sandbox"
    sandbox.write_text("FROM python:3.11-slim@sha256:" + "a" * 64 + "\n", encoding="utf-8")
    monkeypatch.setattr(audit_workflow_security, "ROOT", tmp_path)
    monkeypatch.setattr(audit_workflow_security, "tracked_files", lambda: [dockerfile, sandbox])

    image = audit_workflow_security.docker_snapshot()[0]

    assert image["pinned_digest"] is True
    assert image["pinning_basis"] == "repository_dockerfile"
    assert image["source_dockerfile"] == "Dockerfile.sandbox"


def test_workflow_security_audit_flags_secret_on_pull_request(tmp_path, monkeypatch):
    workflow = tmp_path / ".github/workflows/test.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "on:\n  pull_request:\njobs:\n  test:\n    steps:\n"
        "      - run: echo ${{ secrets.DEPLOY_KEY }}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(audit_workflow_security, "ROOT", tmp_path)
    monkeypatch.setattr(audit_workflow_security, "tracked_files", lambda: [workflow])

    report = audit_workflow_security.audit()

    assert any(item["id"] == "secret-referenced-by-fork-pr-workflow" for item in report["findings"])
