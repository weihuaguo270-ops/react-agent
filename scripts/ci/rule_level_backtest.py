"""Replay a fixed sample against Registry v2 and compare independent labels."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

if __package__:
    from .registry_v2 import ROOT, select, validate_registry
else:
    from registry_v2 import ROOT, select, validate_registry


DEFAULT_SAMPLE = ROOT / "docs/specs/ci/evidence/selector-samples/main-8805e5e9-20261030.json"
DEFAULT_LABELS = ROOT / "docs/specs/ci/evidence/selector-expected-rules-100.json"
DEFAULT_OUTPUT = ROOT / "docs/specs/ci/evidence/phase1-selector-rule-backtest-main-8805e5e9-20261105.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replay(sample_path: Path, labels_path: Path) -> dict:
    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    errors = validate_registry()
    if labels.get("schema_version") != "ci-selector-expected-rules/v1":
        raise ValueError("expected rule label schema is invalid")
    if labels.get("sample_id") != sample.get("sample_id"):
        raise ValueError("label sample identity does not match fixed sample")
    if labels.get("source_sample_sha256") != sha256(sample_path):
        raise ValueError("label source sample hash does not match fixed sample")

    source_rows = {row["pr"]: row for row in sample.get("samples", [])}
    label_rows = {row["pr"]: row for row in labels.get("rows", [])}
    if set(source_rows) != set(label_rows):
        raise ValueError("expected rule labels do not cover exactly the fixed sample")

    rows: list[dict] = []
    false_positive: set[str] = set()
    missed: set[str] = set()
    changed_files = unmapped_files = 0
    comparable_rows = 0
    for pr, source in source_rows.items():
        paths = source.get("changed_paths")
        result = select(paths)
        expected = set(label_rows[pr].get("expected_rules", []))
        raw_selected = result["selected_rules"]
        selected = {
            rule_id
            for rule_id, matched_paths in raw_selected.items()
            if matched_paths or rule_id != result.get("safety_gate_rule_id")
        }
        safety_rule = result.get("safety_gate_rule_id")
        unresolved = label_rows[pr].get("unresolved_paths", [])
        missing = sorted(expected - selected)
        extra = sorted(selected - expected)
        comparable = not unresolved
        if comparable:
            comparable_rows += 1
            false_positive.update(extra)
            missed.update(missing)
        changed_files += len(paths)
        unmapped_files += len(result["unmapped_paths"])
        rows.append(
            {
                "pr": pr,
                "head_sha": source.get("head_sha"),
                "changed_files": len(paths),
                "unmapped_paths": result["unmapped_paths"],
                "expected_rules": sorted(expected),
                "selected_rules": sorted(selected),
                "missing_expected_rules": missing,
                "extra_selected_rules": extra,
                "unresolved_label_paths": unresolved,
                "comparison_status": "comparable" if comparable else "unmeasured",
            }
        )

    measurement_complete = comparable_rows == len(rows)
    comparison_pass = not false_positive and not missed
    conclusion = "pass" if not errors and measurement_complete and unmapped_files == 0 and comparison_pass else "blocked"
    return {
        "schema_version": "ci-selector-rule-backtest/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "spec_revision": "1.5",
        "sample_id": sample.get("sample_id"),
        "sample_size": len(rows),
        "source_sha": sample.get("source_sha"),
        "source_sample_sha256": sha256(sample_path),
        "expected_labels_sha256": sha256(labels_path),
        "registry_sha256": sha256(ROOT / "docs/specs/ci/registry-v2.json"),
        "registry_validation": {"status": "pass" if not errors else "fail", "errors": errors},
        "label_provenance": {
            "schema_version": labels.get("schema_version"),
            "policy": labels.get("policy"),
            "independent": labels.get("label_set_is_independent_of_registry") is True,
        },
        "metrics": {
            "changed_files": changed_files,
            "unmapped_files": unmapped_files,
            "comparable_rows": comparable_rows,
            "unmeasured_rows": len(rows) - comparable_rows,
            "measurement_status": "complete" if measurement_complete else "partial",
            "false_positive_rules": sorted(false_positive),
            "missed_expected_rules": sorted(missed),
            "false_positive_count": len(false_positive),
            "missed_expected_count": len(missed),
        },
        "samples": rows,
        "conclusion": conclusion,
        "gate_eligibility": "eligible" if conclusion == "pass" else "blocked",
        "conclusion_boundary": "Rule-level comparison is measured only for rows with independently classified paths; unresolved paths and selector fallbacks remain blocked.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite existing evidence: {args.output}")
    report = replay(args.sample, args.labels)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"metrics": report["metrics"], "conclusion": report["conclusion"]}, ensure_ascii=False))
    return 0 if report["conclusion"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
