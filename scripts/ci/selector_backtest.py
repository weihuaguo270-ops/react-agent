"""Capture a fixed Phase 0 PR-path sample and replay it offline."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

if __package__:
    from .registry_v2 import ROOT, select, validate_registry
else:
    from registry_v2 import ROOT, select, validate_registry

REPO = "weihuaguo270-ops/react-agent"
SAMPLE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def gh_json(endpoint: str) -> object:
    result = subprocess.run(
        ["gh", "api", endpoint], cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8"
    )
    return json.loads(result.stdout)


def capture_sample(baseline_path: Path, snapshot_id: str, output: Path, repo: str = REPO) -> dict:
    if not SAMPLE_ID_RE.fullmatch(snapshot_id):
        raise ValueError("snapshot id contains unsafe characters")
    if output.exists():
        raise FileExistsError(f"refusing to overwrite frozen selector sample: {output}")
    baseline_bytes = baseline_path.read_bytes()
    baseline = json.loads(baseline_bytes)
    expected_dir = (ROOT / "docs/specs/ci/evidence/snapshots" / snapshot_id).resolve()
    if baseline_path.resolve().parent != expected_dir:
        raise ValueError("baseline must be read from the requested frozen snapshot directory")
    samples = baseline.get("pull_requests", {}).get("samples", [])
    rows = []
    for pr in samples:
        paths: list[str] = []
        page = 1
        while True:
            payload = gh_json(f"repos/{repo}/pulls/{pr['number']}/files?per_page=100&page={page}")
            page_rows = [item["filename"] for item in payload if isinstance(item, dict) and item.get("filename")]
            paths.extend(page_rows)
            if len(page_rows) < 100:
                break
            page += 1
        rows.append({"pr": pr["number"], "head_sha": pr["head_sha"], "changed_paths": sorted(set(paths))})
    return {
        "schema_version": "ci-selector-sample/v1",
        "sample_id": snapshot_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "repository": repo,
        "source_snapshot_id": snapshot_id,
        "source_sha": baseline["default_branch"]["sha"],
        "source_baseline_sha256": sha256_bytes(baseline_bytes),
        "sample_size": len(rows),
        "samples": rows,
    }


def replay(sample_input: Path, sample_id: str) -> dict:
    source_bytes = sample_input.read_bytes()
    source = json.loads(source_bytes)
    if source.get("schema_version") != "ci-selector-sample/v1" or source.get("sample_id") != sample_id:
        raise ValueError("fixed sample identity does not match the requested sample id")
    errors = validate_registry()
    rows = []
    mapped_files = 0
    unmapped_files = 0
    selected_rules: set[str] = set()
    for pr in source.get("samples", []):
        paths = pr.get("changed_paths")
        if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
            raise ValueError(f"sample PR #{pr.get('pr')} has invalid changed_paths")
        result = select(paths)
        mapped_files += len(paths) - len(result["unmapped_paths"])
        unmapped_files += len(result["unmapped_paths"])
        selected_rules.update(result["selected_rules"])
        rows.append({
            "pr": pr["pr"],
            "head_sha": pr["head_sha"],
            "changed_files": len(paths),
            "unmapped_paths": result["unmapped_paths"],
            "selected_rules": sorted(result["selected_rules"]),
        })
    total = mapped_files + unmapped_files
    return {
        "schema_version": "ci-selector-backtest/v2",
        "spec_revision": "1.5",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sample_id": sample_id,
        "sample_size": len(rows),
        "source_sha": source.get("source_sha"),
        "source_sha256": sha256_bytes(source_bytes),
        "registry_sha256": sha256_bytes((ROOT / "docs/specs/ci/registry-v2.json").read_bytes()),
        "registry_validation": {"status": "pass" if not errors else "fail", "errors": errors},
        "metrics": {
            "changed_files": total,
            "mapped_files": mapped_files,
            "unmapped_files": unmapped_files,
            "mapped_coverage": round(mapped_files / total, 4) if total else None,
            "false_positive_rules": None,
            "missed_expected_rules": None,
        },
        "selected_rules": sorted(selected_rules),
        "samples": rows,
        "conclusion": "blocked" if errors or unmapped_files else "pass",
        "conclusion_boundary": "Fixed-input path coverage only. False-positive and missed-rule metrics require an independent expected-rule label set; this replay does not prove CI job correctness or R9 runtime isolation.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("capture")
    capture.add_argument("--snapshot-id", required=True)
    capture.add_argument("--baseline", type=Path, required=True)
    capture.add_argument("--output", type=Path, required=True)
    capture.add_argument("--repo", default=REPO)
    run = commands.add_parser("replay")
    run.add_argument("--sample-id", required=True)
    run.add_argument("--sample-input", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "capture":
        try:
            report = capture_sample(args.baseline, args.snapshot_id, args.output, args.repo)
        except (FileExistsError, ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
            parser.error(str(exc))
    else:
        try:
            report = replay(args.sample_input, args.sample_id)
        except (ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
            parser.error(str(exc))
        if args.output.exists():
            parser.error(f"refusing to overwrite backtest report: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"sample_id": report["sample_id"], "sample_size": report["sample_size"], "metrics": report.get("metrics"), "conclusion": report.get("conclusion", "captured")}, ensure_ascii=False))
    return 0 if args.command == "capture" or report["conclusion"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
