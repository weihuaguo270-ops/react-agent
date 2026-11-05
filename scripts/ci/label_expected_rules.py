"""Build an independent Registry v2 rule-level label set for a fixed sample.

The expected labels intentionally live outside ``registry-v2.json`` and do not
call the selector while deriving expectations.  This keeps the backtest from
proving the selector with its own implementation.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SAMPLE = ROOT / "docs/specs/ci/evidence/selector-samples/main-8805e5e9-20261030.json"
DEFAULT_OUTPUT = ROOT / "docs/specs/ci/evidence/selector-expected-rules-100.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def matches(path: str, patterns: tuple[str, ...]) -> bool:
    normalized = path.replace("\\", "/")
    return any(fnmatch.fnmatchcase(normalized, pattern) or Path(normalized).match(pattern) for pattern in patterns)


def expected_rules_for_path(path: str) -> tuple[set[str], str]:
    """Return independently reviewed rule labels and the classification reason."""

    path = path.replace("\\", "/")
    if matches(path, ("docs/specs/ci/evidence/archive/**",)):
        return set(), "excluded_historical_archive"

    rules: set[str] = set()
    if matches(path, ("scripts/ci/**", "docs/specs/ci/**", ".github/workflows/**", "pyproject.toml")):
        rules.add("ci-pr-readiness")
    if matches(path, ("src/**", "tests/**", "pyproject.toml")):
        rules.add("python-affected-tests")
    if path.startswith("docs/") and not path.startswith("docs/specs/ci/evidence/archive/"):
        rules.add("docs-corpus")
    if matches(path, (".github/workflows/**", "Dockerfile", "Dockerfile.*", "eval/**/Dockerfile*")):
        rules.add("workflow-security")
    if matches(path, ("progress.yaml", "src/react_agent/harness/**", "tests/harness/**", "docs/specs/harness/**")):
        rules.add("harness-stage-gate")
    if matches(path, ("docs/specs/ai-review/**", "scripts/ai_review/**", "tests/test_ai_review_artifact.py")):
        rules.add("ai-review-artifacts")

    return rules, "known_rule_scope" if rules else "unresolved_path_scope"


def build(sample: dict, sample_path: Path) -> dict:
    rows: list[dict] = []
    for item in sample.get("samples", []):
        paths = item.get("changed_paths")
        if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
            raise ValueError(f"sample PR #{item.get('pr')} has invalid changed_paths")
        labels: set[str] = set()
        unresolved: list[str] = []
        excluded: list[str] = []
        classifications: dict[str, str] = {}
        for path in sorted(set(paths)):
            expected, reason = expected_rules_for_path(path)
            labels.update(expected)
            classifications[path] = reason
            if reason == "unresolved_path_scope":
                unresolved.append(path)
            elif reason == "excluded_historical_archive":
                excluded.append(path)
        rows.append(
            {
                "pr": item["pr"],
                "head_sha": item.get("head_sha"),
                "changed_paths": sorted(set(paths)),
                "expected_rules": sorted(labels),
                "unresolved_paths": unresolved,
                "excluded_paths": excluded,
                "path_classification": classifications,
                "comparison_status": "unmeasured" if unresolved else "comparable",
            }
        )

    return {
        "schema_version": "ci-selector-expected-rules/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repository": "weihuaguo270-ops/react-agent",
        "sample_id": sample.get("sample_id"),
        "source_sha": sample.get("source_sha"),
        "source_sample": sample_path.relative_to(ROOT).as_posix(),
        "source_sample_sha256": sha256(sample_path),
        "sample_size": len(rows),
        "policy": "scripts/ci/label_expected_rules.py",
        "policy_basis": "independent path-class policy reviewed separately from registry-v2.json",
        "label_set_is_independent_of_registry": True,
        "rows": rows,
        "metrics": {
            "rows_total": len(rows),
            "comparable_rows": sum(row["comparison_status"] == "comparable" for row in rows),
            "rows_with_unresolved_paths": sum(bool(row["unresolved_paths"]) for row in rows),
            "unresolved_paths": sum(len(row["unresolved_paths"]) for row in rows),
            "excluded_historical_paths": sum(len(row["excluded_paths"]) for row in rows),
            "measurement_status": "complete"
            if all(row["comparison_status"] == "comparable" for row in rows)
            else "partial",
        },
        "conclusion": "pass" if all(row["comparison_status"] == "comparable" for row in rows) else "blocked",
        "conclusion_boundary": "Expected rule labels are independent evidence; unresolved paths remain unmeasured and cannot authorize subset gating.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite existing evidence: {args.output}")
    sample = json.loads(args.sample.read_text(encoding="utf-8"))
    report = build(sample, args.sample)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["metrics"], ensure_ascii=False))
    return 0 if report["conclusion"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
