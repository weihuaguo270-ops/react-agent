"""Replay the PR selector against a frozen sample and estimate CI wall time.

The report is deliberately report-only.  It uses historical GitHub Actions
runs as an estimate of the selected job wall time; it does not claim that a
subset gate is safe until an independent expected-check label set proves that
no required check was missed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from select_pr_checks import load_registry, select_checks


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SAMPLE = ROOT / "docs/specs/ci/evidence/phase0-baseline.json"
DEFAULT_OUTPUT = ROOT / "docs/specs/ci/evidence/selector-cost-backtest.json"
REPO = "weihuaguo270-ops/react-agent"

JOB_TO_CHECK = {
    "PR ready audit": "pr-ready",
    "lint": "lint",
    "typecheck": "typecheck",
    "security": "security",
    "docker-smoke": "docker-smoke",
}


def gh_json(endpoint: str) -> Any:
    result = subprocess.run(
        ["gh", "api", endpoint],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(result.stdout)


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def seconds(start: str, end: str) -> float:
    return max(0.0, (parse_time(end) - parse_time(start)).total_seconds())


def job_check(name: str) -> str | None:
    if name.startswith("test-windows ") or name.startswith("test-windows ("):
        return "test-windows"
    if name.startswith("test ") or name.startswith("test ("):
        return "test"
    return JOB_TO_CHECK.get(name)


def fetch_run(head_sha: str, workflow: str = "test.yml") -> dict[str, Any] | None:
    payload = gh_json(
        f"repos/{REPO}/actions/workflows/{workflow}/runs?head_sha={head_sha}&per_page=20"
    )
    runs = [item for item in payload.get("workflow_runs", []) if item.get("head_sha") == head_sha]
    runs.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return runs[0] if runs else None


def replay(sample: dict[str, Any], sample_size: int) -> dict[str, Any]:
    prs = sample.get("pull_requests", {}).get("samples", [])[:sample_size]
    registry = load_registry()
    rows: list[dict[str, Any]] = []
    for pr in prs:
        number = pr["number"]
        files_payload = gh_json(
            f"repos/{REPO}/pulls/{number}/files?per_page=100"
        )
        changed_files = sorted(
            {item["filename"] for item in files_payload if item.get("filename")}
        )
        selection = select_checks(
            changed_files,
            registry,
            base_sha=pr.get("base_sha"),
            head_sha=pr.get("head_sha"),
            pr_number=number,
            event_name="pull_request",
        )
        run = fetch_run(pr["head_sha"])
        if not run:
            rows.append(
                {
                    "pr": number,
                    "head_sha": pr["head_sha"],
                    "changed_files": len(changed_files),
                    "status": selection["status"],
                    "unmapped_paths": selection["unmapped_paths"],
                    "selected_checks": selection["selected_checks"],
                    "run_id": None,
                    "measurement": "unavailable",
                }
            )
            continue
        jobs_payload = gh_json(
            f"repos/{REPO}/actions/runs/{run['id']}/jobs?per_page=100"
        )
        jobs = [
            {
                "name": job.get("name"),
                "check": job_check(job.get("name", "")),
                "duration_seconds": seconds(job["started_at"], job["completed_at"])
                if job.get("started_at") and job.get("completed_at")
                else None,
                "conclusion": job.get("conclusion"),
            }
            for job in jobs_payload.get("jobs", [])
        ]
        measured = [job for job in jobs if job["duration_seconds"] is not None]
        full_wall = seconds(run["created_at"], run["updated_at"])
        selected = set(selection["selected_checks"])
        selected_jobs = [job for job in measured if job["check"] in selected]
        subset_wall = max((job["duration_seconds"] for job in selected_jobs), default=None)
        improvement = (
            round((full_wall - subset_wall) / full_wall, 4)
            if subset_wall is not None and full_wall > 0
            else None
        )
        failed_checks = sorted(
            {
                job["check"]
                for job in measured
                if job["conclusion"] not in {"success", "skipped", "neutral"} and job["check"]
            }
        )
        missed_historical_failures = sorted(set(failed_checks) - selected)
        rows.append(
            {
                "pr": number,
                "head_sha": pr["head_sha"],
                "changed_files": len(changed_files),
                "status": selection["status"],
                "unmapped_paths": selection["unmapped_paths"],
                "selected_checks": selection["selected_checks"],
                "run_id": run["id"],
                "run_conclusion": run.get("conclusion"),
                "full_wall_seconds": round(full_wall, 2),
                "selected_job_wall_seconds": round(subset_wall, 2) if subset_wall is not None else None,
                "estimated_improvement": improvement,
                "failed_checks": failed_checks,
                "missed_historical_failures": missed_historical_failures,
                "measurement": "historical_job_estimate",
            }
        )
    measured_rows = [
        row
        for row in rows
        if row.get("measurement") == "historical_job_estimate"
        and row.get("status") == "mapped"
        and row.get("estimated_improvement") is not None
    ]
    improvements = [row["estimated_improvement"] for row in measured_rows]
    failures_outside_selection = sorted(
        {item for row in rows for item in row.get("missed_historical_failures", [])}
    )
    mapped_rows = [row for row in rows if row.get("status") == "mapped"]
    mapped_without_duration = [
        row for row in mapped_rows if row.get("estimated_improvement") is None
    ]
    return {
        "schema_version": "ci-selector-cost-backtest/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repository": REPO,
        "sample_source": "docs/specs/ci/evidence/phase0-baseline.json",
        "sample_size_requested": sample_size,
        "sample_size_replayed": len(rows),
        "selector_mode": registry.get("mode", "report-only"),
        "metrics": {
            "mapped_prs_replayed": len(mapped_rows),
            "mapped_prs_with_duration_estimate": len(measured_rows),
            "mapped_prs_without_duration_estimate": len(mapped_without_duration),
            "median_estimated_improvement": round(median(improvements), 4) if improvements else None,
            "historical_failures_outside_selection": failures_outside_selection,
            "zero_missed_required_checks_proven": False,
            "subset_gate_eligible": False,
        },
        "conclusion": "blocked",
        "conclusion_boundary": (
            "Historical job durations estimate a possible wall-time reduction. "
            "Failures outside a selected set are diagnostic only: the repository "
            "has no independent expected-check label set, so they do not prove a "
            "selector miss or safety. The selector remains report-only."
        ),
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    parser.add_argument("--sample-size", type=int, default=20)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    sample = json.loads(args.sample.read_text(encoding="utf-8"))
    report = replay(sample, args.sample_size)
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite existing evidence: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["metrics"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
