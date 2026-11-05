from __future__ import annotations

import hashlib
import json

from scripts.ci.label_expected_rules import expected_rules_for_path
from scripts.ci.rule_level_backtest import replay
from scripts.ci.ci_stage_gate import validate_rule_level_backtest


def test_expected_rule_policy_does_not_import_registry_semantics():
    assert expected_rules_for_path("docs/specs/ci/spec.md")[0] == {"ci-pr-readiness", "docs-corpus"}
    assert expected_rules_for_path("docs/specs/ci/evidence/archive/2026-10-22/phase0-baseline.md")[1] == "excluded_historical_archive"
    assert expected_rules_for_path("unknown/file.xyz")[1] == "unresolved_path_scope"


def test_rule_level_replay_keeps_unresolved_rows_unmeasured(tmp_path, monkeypatch):
    sample_path = tmp_path / "sample.json"
    sample = {
        "schema_version": "ci-selector-sample/v1",
        "sample_id": "sample",
        "source_sha": "a" * 40,
        "samples": [{"pr": 1, "head_sha": "b" * 40, "changed_paths": ["docs/specs/ci/spec.md", "unknown/file.xyz"]}],
    }
    sample_path.write_text(json.dumps(sample), encoding="utf-8")
    labels_path = tmp_path / "labels.json"
    labels_path.write_text(json.dumps({
        "schema_version": "ci-selector-expected-rules/v1",
        "sample_id": "sample",
        "source_sample_sha256": hashlib.sha256(sample_path.read_bytes()).hexdigest(),
        "policy": "independent",
        "label_set_is_independent_of_registry": True,
        "rows": [{
            "pr": 1,
            "expected_rules": ["ci-pr-readiness", "docs-corpus"],
            "unresolved_paths": ["unknown/file.xyz"],
        }],
    }), encoding="utf-8")
    registry = tmp_path / "docs/specs/ci/registry-v2.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(json.dumps({"schema_version": "spec-registry/v2", "directions": {"ci": {"rules": [], "unmapped": [], "exceptions": []}}}), encoding="utf-8")
    monkeypatch.setattr("scripts.ci.rule_level_backtest.ROOT", tmp_path)
    monkeypatch.setattr("scripts.ci.rule_level_backtest.validate_registry", lambda: [])
    monkeypatch.setattr("scripts.ci.rule_level_backtest.select", lambda paths: {"selected_rules": {"ci-pr-readiness": []}, "unmapped_paths": ["unknown/file.xyz"], "safety_gate_rule_id": "ci-pr-readiness"})

    report = replay(sample_path, labels_path)

    assert report["metrics"]["measurement_status"] == "partial"
    assert report["conclusion"] == "blocked"


def test_gate_rejects_labels_that_claim_registry_independence_without_provenance(tmp_path):
    assert not validate_rule_level_backtest(
        {"schema_version": "ci-selector-rule-backtest/v1"},
        {"schema_version": "ci-selector-expected-rules/v1", "label_set_is_independent_of_registry": False},
        {},
        "sample",
        tmp_path / "sample.json",
        tmp_path / "labels.json",
        "1.5",
    )
