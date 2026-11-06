"""Aggregate report-only selector observations without enabling a PR gate.

The aggregator is deliberately fail-closed. It accepts only paired selector
and independent expected-check artifacts bound to the same base/head SHA. A
report can describe progress, but it is eligible only after the complete
observation-window requirements in the CI Spec are met.
"""

from __future__ import annotations

import argparse
import json
import statistics
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

FULL_CHECKS = {
    "pr-ready",
    "lint",
    "test",
    "test-windows",
    "typecheck",
    "security",
    "docker-smoke",
    "docs-eval",
}
SCHEMA = "ci-shadow-observation/v1"


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("artifact must contain a JSON object")
    return payload


def _parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("generated_at must be an ISO timestamp")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 40 or any(c not in "0123456789abcdefABCDEF" for c in value):
        raise ValueError(f"{name} must be a full commit SHA")
    return value.lower()


def _key(payload: dict[str, Any]) -> tuple[int, str]:
    number = payload.get("pr_number")
    if not isinstance(number, int) or isinstance(number, bool):
        raise ValueError("pr_number must be an integer")
    return number, _sha(payload.get("head_sha"), "head_sha")


def _runtime_improvement(payload: dict[str, Any]) -> float | None:
    """Read an explicitly paired full-vs-selected runtime improvement.

    The aggregator refuses to derive this from workflow wall time because the
    report-only artifact does not establish a same-attempt job pairing.
    """
    value = payload.get("runtime_improvement")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1:
        return float(value)
    return None


def validate_pair(selector: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    if selector.get("schema_version") != "ci-pr-check-scope/v1":
        raise ValueError("selector schema_version is unsupported")
    if expected.get("schema_version") != "ci-expected-pr-checks/v1":
        raise ValueError("expected-check schema_version is unsupported")
    selector_key = _key(selector)
    if _key(expected) != selector_key:
        raise ValueError("selector and expected-check artifacts are not bound to the same PR/head")
    base_sha = _sha(selector.get("base_sha"), "base_sha")
    if _sha(expected.get("base_sha"), "base_sha") != base_sha:
        raise ValueError("selector and expected-check base SHA differ")
    changed = selector.get("changed_files")
    expected_changed = expected.get("changed_files")
    if not isinstance(changed, list) or not all(isinstance(item, str) for item in changed):
        raise ValueError("selector changed_files is invalid")
    if sorted(changed) != sorted(expected_changed or []):
        raise ValueError("selector and expected-check changed paths differ")
    selected = selector.get("selected_checks")
    expected_checks = expected.get("expected_checks")
    if not isinstance(selected, list) or not all(isinstance(item, str) for item in selected):
        raise ValueError("selector selected_checks is invalid")
    if not isinstance(expected_checks, list) or not all(isinstance(item, str) for item in expected_checks):
        raise ValueError("expected_checks is invalid")
    if not set(selected) <= FULL_CHECKS or not set(expected_checks) <= FULL_CHECKS:
        raise ValueError("unknown check in selector or expected-check artifact")
    generated = max(_parse_timestamp(selector.get("generated_at")), _parse_timestamp(expected.get("generated_at")))
    missing = sorted(set(expected_checks) - set(selected))
    selected_is_subset = set(selected) < FULL_CHECKS
    return {
        "pr": selector_key[0],
        "head_sha": selector_key[1],
        "base_sha": base_sha,
        "generated_at": generated.isoformat(),
        "change_class": str(expected.get("change_class") or "unknown"),
        "selector_status": selector.get("status"),
        "selected_checks": sorted(set(selected)),
        "expected_checks": sorted(set(expected_checks)),
        "missing_checks": missing,
        "unmapped_paths": sorted(selector.get("unmapped_paths") or []),
        "selected_is_strict_subset": selected_is_subset,
        "runtime_improvement": _runtime_improvement(selector),
    }


def aggregate(selector_paths: list[Path], expected_paths: list[Path], *, today: date | None = None) -> dict[str, Any]:
    selectors: dict[tuple[int, str], tuple[Path, dict[str, Any]]] = {}
    selector_heads: dict[str, Path] = {}
    invalid: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for path in selector_paths:
        try:
            payload = _read(path)
            key = _key(payload)
            if key[1] in selector_heads:
                excluded.append({"path": str(path), "reason": "duplicate head SHA; rerun excluded from sample"})
                continue
            selector_heads[key[1]] = path
            if key in selectors:
                excluded.append({"path": str(path), "reason": "duplicate selector artifact"})
            else:
                selectors[key] = (path, payload)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            invalid.append({"path": str(path), "reason": str(exc)})

    expected_by_key: dict[tuple[int, str], tuple[Path, dict[str, Any]]] = {}
    for path in expected_paths:
        try:
            payload = _read(path)
            key = _key(payload)
            if key in expected_by_key:
                excluded.append({"path": str(path), "reason": "duplicate expected-check artifact"})
            else:
                expected_by_key[key] = (path, payload)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            invalid.append({"path": str(path), "reason": str(exc)})

    rows: list[dict[str, Any]] = []
    for key, (selector_path, selector) in sorted(selectors.items()):
        expected_entry = expected_by_key.get(key)
        if expected_entry is None:
            invalid.append({"path": str(selector_path), "reason": "missing expected-check artifact"})
            continue
        try:
            rows.append(validate_pair(selector, expected_entry[1]))
        except ValueError as exc:
            invalid.append({"path": str(selector_path), "reason": str(exc)})

    rows.sort(key=lambda row: row["generated_at"])
    starts = [_parse_timestamp(row["generated_at"]) for row in rows]
    window_start = min(starts).date().isoformat() if starts else None
    window_end = max(starts).date().isoformat() if starts else None
    current_date = today or datetime.now(timezone.utc).date()
    if window_start:
        elapsed_days = (current_date - date.fromisoformat(window_start)).days + 1
    else:
        elapsed_days = 0
    unique_heads = {row["head_sha"] for row in rows}
    classes = {row["change_class"] for row in rows if row["selected_is_strict_subset"]}
    comparable = [row["runtime_improvement"] for row in rows if row["runtime_improvement"] is not None and row["selected_is_strict_subset"]]
    missing = sorted({item for row in rows for item in row["missing_checks"]})
    unmapped = sum(len(row["unmapped_paths"]) for row in rows)
    criteria = {
        "observation_days_at_least_14": elapsed_days >= 14,
        "unique_head_shas_at_least_10": len(unique_heads) >= 10,
        "three_shrinking_rule_categories": len(classes) >= 3,
        "zero_expected_check_misses": not missing,
        "ten_comparable_runtime_shas": len(comparable) >= 10,
        "median_runtime_improvement_at_least_20_percent": False,
        "no_invalid_samples": not invalid,
    }
    median_runtime_improvement = None
    if len(comparable) >= 10:
        # The workflow that produces this field must pair full and selected
        # job runtimes from the same head and run attempt.
        median_runtime_improvement = statistics.median(comparable)
        criteria["median_runtime_improvement_at_least_20_percent"] = median_runtime_improvement >= 0.2
    eligible = bool(rows) and all(criteria.values())
    return {
        "schema_version": SCHEMA,
        "mode": "report-only",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_start": window_start,
        "window_end": window_end,
        "elapsed_calendar_days": elapsed_days,
        "sample_count": len(rows),
        "unique_head_sha_count": len(unique_heads),
        "rule_categories_with_strict_subset": sorted(classes),
        "invalid_samples": invalid,
        "excluded_samples": excluded,
        "rows": rows,
        "metrics": {
            "unmapped_path_count": unmapped,
            "missing_expected_checks": missing,
            "comparable_runtime_count": len(comparable),
            "median_runtime_improvement": median_runtime_improvement,
            "criteria": criteria,
            "subset_gate_eligible": eligible,
        },
        "conclusion": "pass" if eligible else "blocked",
        "conclusion_boundary": "This report is report-only evidence. It never enables a subset gate or changes Branch Protection.",
    }


def _paths(value: list[str]) -> list[Path]:
    return [Path(item) for item in value]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selector", action="append", required=True)
    parser.add_argument("--expected", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = aggregate(_paths(args.selector), _paths(args.expected))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["metrics"], ensure_ascii=False))
    return 0 if report["conclusion"] in {"pass", "blocked"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
