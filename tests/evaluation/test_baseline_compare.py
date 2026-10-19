"""Tests for baseline comparison."""
import json
from pathlib import Path

import pytest

from react_agent.harness.evaluation.baseline_compare import (
    compare_baseline,
    compare_repair_evidence,
)


@pytest.fixture
def tmp_results(tmp_path):
    """Create temporary result files."""
    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    return baseline, current


def test_compare_baseline_detects_regression(tmp_results):
    baseline_path, current_path = tmp_results

    # Baseline passed
    baseline_path.write_text(json.dumps({
        "status": "succeeded",
        "exit_code": 0,
    }), encoding="utf-8")

    # Current failed (regression)
    current_path.write_text(json.dumps({
        "status": "failed",
        "exit_code": 1,
    }), encoding="utf-8")

    result = compare_baseline(baseline_path, current_path)

    assert result["schema_version"] == "baseline-compare/v1"
    assert result["diff"]["test_status_changed"] is True
    assert result["diff"]["exit_code_changed"] is True
    assert result["summary"]["regression_detected"] is True
    assert result["summary"]["improvement_detected"] is False
    assert result["summary"]["status"] == "regression"


def test_compare_baseline_detects_improvement(tmp_results):
    baseline_path, current_path = tmp_results

    # Baseline failed
    baseline_path.write_text(json.dumps({
        "status": "failed",
        "exit_code": 1,
    }), encoding="utf-8")

    # Current passed (improvement)
    current_path.write_text(json.dumps({
        "status": "succeeded",
        "exit_code": 0,
    }), encoding="utf-8")

    result = compare_baseline(baseline_path, current_path)

    assert result["diff"]["test_status_changed"] is True
    assert result["diff"]["exit_code_changed"] is True
    assert result["summary"]["regression_detected"] is False
    assert result["summary"]["improvement_detected"] is True
    assert result["summary"]["status"] == "improvement"


def test_compare_baseline_detects_no_change(tmp_results):
    baseline_path, current_path = tmp_results

    # Both passed
    for path in [baseline_path, current_path]:
        path.write_text(json.dumps({
            "status": "succeeded",
            "exit_code": 0,
        }), encoding="utf-8")

    result = compare_baseline(baseline_path, current_path)

    assert result["diff"]["test_status_changed"] is False
    assert result["diff"]["exit_code_changed"] is False
    assert result["summary"]["regression_detected"] is False
    assert result["summary"]["improvement_detected"] is False
    assert result["summary"]["status"] == "unchanged"


def test_compare_repair_evidence(tmp_path):
    """Test repair evidence comparison."""
    evidence_dir = tmp_path / "repair_evidence"
    before_dir = evidence_dir / "before"
    after_dir = evidence_dir / "after"

    before_dir.mkdir(parents=True)
    after_dir.mkdir(parents=True)

    # Before: failed
    (before_dir / "test-result.json").write_text(json.dumps({
        "status": "failed",
        "exit_code": 1,
    }), encoding="utf-8")

    # After: passed
    (after_dir / "test-result.json").write_text(json.dumps({
        "status": "succeeded",
        "exit_code": 0,
    }), encoding="utf-8")

    result = compare_repair_evidence(evidence_dir)

    assert result["schema_version"] == "baseline-compare/v1"
    assert result["summary"]["improvement_detected"] is True
    assert "repair_context" in result
    assert result["repair_context"]["evidence_dir"] == str(evidence_dir)


def test_compare_repair_evidence_missing_files(tmp_path):
    """Test handling of missing evidence files."""
    evidence_dir = tmp_path / "repair_evidence"
    evidence_dir.mkdir()

    result = compare_repair_evidence(evidence_dir)

    assert "error" in result
    assert result["before_exists"] is False
    assert result["after_exists"] is False
