"""Baseline comparison for repair/reverify workflows.

Compare baseline execution results with current execution to detect
regressions and improvements.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def compare_baseline(
    baseline_path: Path,
    current_path: Path,
) -> dict[str, Any]:
    """Compare baseline and current execution results.

    Args:
        baseline_path: Path to baseline execution result
        current_path: Path to current execution result

    Returns:
        Comparison report with diffs and summary
    """
    baseline = _load_result(baseline_path)
    current = _load_result(current_path)

    # Compare test status
    test_status_changed = baseline.get("status") != current.get("status")
    exit_code_changed = baseline.get("exit_code") != current.get("exit_code")

    # Detect regression or improvement
    regression = _is_regression(baseline, current)
    improvement = _is_improvement(baseline, current)

    return {
        "schema_version": "baseline-compare/v1",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "baseline": {
            "path": str(baseline_path),
            "status": baseline.get("status"),
            "exit_code": baseline.get("exit_code"),
        },
        "current": {
            "path": str(current_path),
            "status": current.get("status"),
            "exit_code": current.get("exit_code"),
        },
        "diff": {
            "test_status_changed": test_status_changed,
            "exit_code_changed": exit_code_changed,
        },
        "summary": {
            "regression_detected": regression,
            "improvement_detected": improvement,
            "status": "regression" if regression else ("improvement" if improvement else "unchanged"),
        },
    }


def _load_result(path: Path) -> dict[str, Any]:
    """Load execution result from JSON file."""
    if not path.exists():
        raise FileNotFoundError(f"Result file not found: {path}")

    return json.loads(path.read_text(encoding="utf-8"))


def _is_regression(baseline: dict, current: dict) -> bool:
    """Check if current execution is a regression from baseline."""
    baseline_status = baseline.get("status", "")
    current_status = current.get("status", "")

    # Regression: baseline passed, current failed
    if baseline_status == "succeeded" and current_status in ("failed", "error"):
        return True

    # Regression: baseline exit 0, current non-zero
    baseline_exit = baseline.get("exit_code", 1)
    current_exit = current.get("exit_code", 1)
    if baseline_exit == 0 and current_exit != 0:
        return True

    return False


def _is_improvement(baseline: dict, current: dict) -> bool:
    """Check if current execution is an improvement over baseline."""
    baseline_status = baseline.get("status", "")
    current_status = current.get("status", "")

    # Improvement: baseline failed, current passed
    if baseline_status in ("failed", "error") and current_status == "succeeded":
        return True

    # Improvement: baseline non-zero exit, current exit 0
    baseline_exit = baseline.get("exit_code", 1)
    current_exit = current.get("exit_code", 1)
    if baseline_exit != 0 and current_exit == 0:
        return True

    return False


def compare_repair_evidence(evidence_dir: Path) -> dict[str, Any]:
    """Compare before/after repair evidence in a repair directory.

    Args:
        evidence_dir: Directory containing before/ and after/ subdirs

    Returns:
        Comparison report
    """
    before_result = evidence_dir / "before" / "test-result.json"
    after_result = evidence_dir / "after" / "test-result.json"

    if not before_result.exists() or not after_result.exists():
        return {
            "schema_version": "baseline-compare/v1",
            "error": "Missing before or after test results",
            "before_exists": before_result.exists(),
            "after_exists": after_result.exists(),
        }

    comparison = compare_baseline(before_result, after_result)

    # Add repair-specific context
    comparison["repair_context"] = {
        "evidence_dir": str(evidence_dir),
        "before_path": str(before_result.relative_to(evidence_dir)),
        "after_path": str(after_result.relative_to(evidence_dir)),
    }

    return comparison


__all__ = ["compare_baseline", "compare_repair_evidence"]
