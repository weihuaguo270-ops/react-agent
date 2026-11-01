"""Build an independent expected-check label set for a fixed PR sample."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from expected_pr_checks import expected_checks
from select_pr_checks import load_registry, select_checks


ROOT = Path(__file__).resolve().parents[2]
REPO = "weihuaguo270-ops/react-agent"
DEFAULT_SAMPLE = ROOT / "docs/specs/ci/evidence/phase0-baseline.json"
DEFAULT_OUTPUT = ROOT / "docs/specs/ci/evidence/selector-expected-checks-100.json"


def gh_json(endpoint: str) -> object:
    result = subprocess.run(
        ["gh", "api", endpoint], cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8"
    )
    return json.loads(result.stdout)


def build(sample: dict, sample_size: int) -> dict:
    registry = load_registry()
    rows = []
    for pr in sample.get("pull_requests", {}).get("samples", [])[:sample_size]:
        live_pr = gh_json(f"repos/{REPO}/pulls/{pr['number']}")
        live_head = live_pr.get("head", {}).get("sha")
        live_base = live_pr.get("base", {}).get("sha")
        payload = gh_json(f"repos/{REPO}/pulls/{pr['number']}/files?per_page=100")
        paths = sorted({item["filename"] for item in payload if item.get("filename")})
        expected = expected_checks(paths)
        selected = select_checks(paths, registry, base_sha=pr.get("base_sha"), head_sha=pr.get("head_sha"), pr_number=pr["number"], event_name="pull_request")
        expected_set = set(expected["checks"])
        selected_set = set(selected["selected_checks"])
        rows.append(
            {
                "pr": pr["number"],
                "head_sha": pr.get("head_sha"),
                "base_sha": pr.get("base_sha"),
                "observed_head_sha": live_head,
                "observed_base_sha": live_base,
                "input_status": "current_head_matches_sample" if live_head == pr.get("head_sha") else "stale_head",
                "changed_paths": paths,
                "change_class": expected["class"],
                "label_reason": expected["reason"],
                "expected_checks": expected["checks"],
                "selected_checks": selected["selected_checks"],
                "unmapped_paths": selected["unmapped_paths"],
                "missing_expected_checks": sorted(expected_set - selected_set),
                "extra_selected_checks": sorted(selected_set - expected_set),
                "selector_status": selected["status"],
            }
        )
    comparable_rows = [row for row in rows if row["input_status"] == "current_head_matches_sample"]
    missing = sorted({check for row in comparable_rows for check in row["missing_expected_checks"]})
    stale_prs = [row["pr"] for row in rows if row["input_status"] != "current_head_matches_sample"]
    return {
        "schema_version": "ci-selector-expected-checks/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repository": REPO,
        "sample_source": "docs/specs/ci/evidence/phase0-baseline.json",
        "sample_size": len(rows),
        "policy": "scripts/ci/expected_pr_checks.py",
        "metrics": {
            "rows_with_missing_expected_checks": sum(bool(row["missing_expected_checks"]) for row in rows),
            "missing_expected_checks": missing,
            "stale_sample_prs": stale_prs,
            "zero_expected_check_misses": not missing and not stale_prs,
            "label_set_is_independent_of_registry": True,
        },
        "conclusion": "pass" if not missing and not stale_prs else "blocked",
        "conclusion_boundary": "Labels express the minimum deterministic checks required by the change class; they do not authorize subset gating or change Branch Protection.",
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    parser.add_argument("--sample-size", type=int, default=100)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = build(json.loads(args.sample.read_text(encoding="utf-8")), args.sample_size)
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite existing evidence: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["metrics"], ensure_ascii=False))
    return 0 if report["conclusion"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
