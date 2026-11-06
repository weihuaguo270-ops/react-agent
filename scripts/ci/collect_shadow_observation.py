"""Collect and aggregate live report-only selector artifacts from GitHub Actions.

This command never changes required checks. It keeps one sample per PR
``head_sha``, preserves reruns as excluded evidence, and derives a runtime
estimate only when all deterministic jobs in the same workflow attempt have
successful timestamps. Missing or stale inputs remain blocked.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__:
    from .aggregate_shadow_observation import aggregate
else:  # pragma: no cover - exercised when invoked as a file from the workflow
    from aggregate_shadow_observation import aggregate

DEFAULT_REPO = "weihuaguo270-ops/react-agent"
DEFAULT_WORKFLOW = "test.yml"
CHECKS = {
    "PR ready audit": "pr-ready",
    "lint": "lint",
    "typecheck": "typecheck",
    "security": "security",
    "docker-smoke": "docker-smoke",
}
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
RUNTIME_CHECKS = FULL_CHECKS - {"docs-eval"}


def gh_json(endpoint: str) -> Any:
    result = subprocess.run(
        ["gh", "api", endpoint],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(result.stdout)


def job_check(name: str) -> str | None:
    if name.startswith("test-windows"):
        return "test-windows"
    if name.startswith("test "):
        return "test"
    return CHECKS.get(name)


def duration(job: dict[str, Any]) -> float | None:
    started = job.get("started_at")
    completed = job.get("completed_at")
    if not started or not completed:
        return None
    try:
        start = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(completed).replace("Z", "+00:00"))
    except ValueError:
        return None
    value = (end - start).total_seconds()
    return value if value >= 0 else None


def runtime_observation(
    selector: dict[str, Any],
    jobs: list[dict[str, Any]],
    run: dict[str, Any],
    *,
    expected_checks: set[str] | None = None,
) -> dict[str, Any]:
    selected = set(selector.get("selected_checks") or [])
    measured: list[tuple[str, float, str | None]] = []
    incomplete = False
    discovered: set[str] = set()
    for job in jobs:
        check = job_check(str(job.get("name") or ""))
        if not check:
            continue
        discovered.add(check)
        seconds = duration(job)
        conclusion = job.get("conclusion")
        if seconds is None or conclusion not in {"success", "skipped", "neutral"}:
            incomplete = True
        else:
            measured.append((check, seconds, conclusion))
    expected = set(expected_checks or RUNTIME_CHECKS)
    missing_checks = sorted(expected - discovered)
    incomplete = incomplete or bool(missing_checks)
    full_seconds = sum(item[1] for item in measured)
    selected_seconds = sum(item[1] for item in measured if item[0] in selected)
    comparable = not incomplete and full_seconds > 0 and selected < expected
    result = {
        "workflow_run_id": run.get("id"),
        "run_attempt": run.get("run_attempt"),
        "runtime_source": "same_workflow_attempt_job_estimate" if comparable else None,
        "runtime_full_seconds": round(full_seconds, 2) if full_seconds else None,
        "runtime_selected_seconds": round(selected_seconds, 2) if comparable else None,
        "runtime_improvement": round(1 - selected_seconds / full_seconds, 4) if comparable else None,
        "runtime_comparable": comparable,
        "runtime_incomplete": incomplete,
        "runtime_missing_checks": missing_checks,
    }
    selector.update(result)
    return selector


def download_artifact(repo: str, run_id: int, destination: Path) -> tuple[Path, Path]:
    destination.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "gh",
            "run",
            "download",
            str(run_id),
            "--repo",
            repo,
            "--name",
            "pr-check-scope",
            "--dir",
            str(destination),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    selector_path = destination / "pr-check-scope.json"
    expected_path = destination / "expected-pr-checks.json"
    if not selector_path.is_file() or not expected_path.is_file():
        raise ValueError("scope artifact is missing selector or expected-check JSON")
    return selector_path, expected_path


def collect(repo: str, workflow: str, output: Path, *, limit: int = 100) -> dict[str, Any]:
    payload = gh_json(f"repos/{repo}/actions/workflows/{workflow}/runs?event=pull_request&per_page={limit}")
    runs = [run for run in payload.get("workflow_runs", []) if run.get("event") == "pull_request"]
    runs.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    artifact_root = output.parent / f"{output.stem}-samples"
    artifact_root.mkdir(parents=True, exist_ok=True)
    selectors: list[Path] = []
    expected: list[Path] = []
    seen_heads: set[str] = set()
    excluded: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="shadow-download-") as temp:
        for run in runs:
            run_id = run.get("id")
            head_sha = str(run.get("head_sha") or "").lower()
            if not isinstance(run_id, int) or not head_sha:
                excluded.append({"run_id": run_id, "reason": "missing run id or head SHA"})
                continue
            if head_sha in seen_heads:
                excluded.append({"run_id": run_id, "head_sha": head_sha, "reason": "rerun excluded; head SHA already sampled"})
                continue
            try:
                run_dir = Path(temp) / str(run_id)
                selector_path, expected_path = download_artifact(repo, run_id, run_dir)
                selector = json.loads(selector_path.read_text(encoding="utf-8"))
                labels = json.loads(expected_path.read_text(encoding="utf-8"))
                selector_head = str(selector.get("head_sha") or "").lower()
                expected_head = str(labels.get("head_sha") or "").lower()
                if selector_head != head_sha or expected_head != head_sha:
                    raise ValueError("run and selector/expected-check artifacts are not bound to the same head SHA")
                jobs = gh_json(f"repos/{repo}/actions/runs/{run_id}/jobs?per_page=100").get("jobs", [])
                expected_checks = labels.get("expected_checks")
                if not isinstance(expected_checks, list) or not all(isinstance(item, str) for item in expected_checks):
                    raise ValueError("expected-check artifact has invalid expected_checks")
                enriched = runtime_observation(
                    selector,
                    jobs,
                    run,
                    expected_checks=set(expected_checks) & RUNTIME_CHECKS,
                )
                enriched["base_sha"] = selector.get("base_sha")
                sample_dir = artifact_root / str(run_id)
                sample_dir.mkdir(parents=True, exist_ok=True)
                selector_out = sample_dir / "pr-check-scope.json"
                expected_out = sample_dir / "expected-pr-checks.json"
                selector_out.write_text(json.dumps(enriched, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                expected_out.write_text(json.dumps(labels, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                selectors.append(selector_out)
                expected.append(expected_out)
                # Only reserve a head after a complete paired artifact was
                # collected. If the newest rerun has a missing artifact, an
                # older attempt may still provide the one valid sample.
                seen_heads.add(head_sha)
            except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
                excluded.append({"run_id": run_id, "head_sha": head_sha, "reason": str(exc)})

    report = aggregate(selectors, expected)
    report["repository"] = repo
    report["workflow"] = workflow
    report["source_run_count"] = len(runs)
    report["excluded_runs"] = excluded
    report["collected_at"] = datetime.now(timezone.utc).isoformat()
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--workflow", default=DEFAULT_WORKFLOW)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = collect(args.repo, args.workflow, args.output, limit=args.limit)
    print(json.dumps({"conclusion": report["conclusion"], "metrics": report["metrics"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
