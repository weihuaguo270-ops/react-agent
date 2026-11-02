"""Run the bounded CI subsystem stage gate and persist a report."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

if __package__:
    from .registry_v2 import ROOT, select, validate_registry
else:
    from registry_v2 import ROOT, select, validate_registry

REPORT_DIR = ROOT / "artifacts/ci/stage-gates"
PROGRESS = ROOT / "docs/specs/ci/progress.yaml"


def canonical_bytes(path: Path) -> bytes:
    """Hash text evidence independently of the checkout's newline policy."""
    return path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def verify_snapshot(snapshot_id: str, expected_spec_revision: str | None = None) -> dict:
    snapshots_root = (ROOT / "docs/specs/ci/evidence/snapshots").resolve()
    snapshot_dir = (snapshots_root / snapshot_id).resolve()
    if not snapshot_dir.is_relative_to(snapshots_root) or not snapshot_dir.is_dir():
        return {"status": "failed", "reason": "snapshot directory is missing or escapes the snapshot root"}
    manifest_path = snapshot_dir / "manifest.json"
    baseline_path = snapshot_dir / "phase0-baseline.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "failed", "reason": f"snapshot metadata is unreadable: {exc}"}
    if manifest.get("evidence_kind") != "frozen_snapshot" or manifest.get("snapshot_id") != snapshot_id:
        return {"status": "failed", "reason": "snapshot manifest identity does not match the requested snapshot"}
    target = manifest.get("target")
    source_hash = manifest.get("source_baseline_sha256")
    required_metadata = (
        manifest.get("spec_revision"),
        manifest.get("created_at"),
        manifest.get("repository"),
        manifest.get("sample_definition"),
        target.get("name") if isinstance(target, dict) else None,
    )
    if not all(required_metadata):
        return {"status": "failed", "reason": "snapshot provenance metadata is incomplete"}
    if not isinstance(manifest.get("repository"), str) or not isinstance(manifest.get("sample_definition"), dict):
        return {"status": "failed", "reason": "snapshot provenance metadata has invalid types"}
    try:
        datetime.fromisoformat(manifest["created_at"].replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return {"status": "failed", "reason": "snapshot creation timestamp is invalid"}
    if expected_spec_revision and manifest.get("spec_revision") != expected_spec_revision:
        return {"status": "failed", "reason": "snapshot Spec revision does not match the active acceptance revision"}
    target_sha = target.get("sha") if isinstance(target, dict) else None
    if not isinstance(target_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", target_sha):
        return {"status": "failed", "reason": "snapshot target SHA is missing or invalid"}
    if target_sha != baseline.get("default_branch", {}).get("sha"):
        return {"status": "failed", "reason": "manifest target SHA does not match baseline content"}
    if not isinstance(source_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", source_hash):
        return {"status": "failed", "reason": "snapshot source baseline hash is missing or invalid"}
    if source_hash != hashlib.sha256(canonical_bytes(baseline_path)).hexdigest():
        return {"status": "failed", "reason": "snapshot source baseline hash does not match the frozen baseline"}
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        return {"status": "failed", "reason": "manifest has no artifact integrity records"}
    verified = []
    for name, metadata in artifacts.items():
        artifact_path = (snapshot_dir / name).resolve()
        if artifact_path.parent != snapshot_dir or not artifact_path.is_file():
            return {"status": "failed", "reason": f"snapshot artifact is missing or unsafe: {name}"}
        canonical = canonical_bytes(artifact_path)
        digest = hashlib.sha256(canonical).hexdigest()
        if digest != metadata.get("sha256") or len(canonical) != metadata.get("bytes"):
            return {"status": "failed", "reason": f"snapshot artifact integrity mismatch: {name}"}
        verified.append(name)
    return {
        "status": "passed",
        "snapshot_id": snapshot_id,
        "target_sha": target_sha,
        "spec_revision": manifest.get("spec_revision"),
        "source_baseline_sha256": source_hash,
        "verified_artifacts": verified,
    }


def run(stage: str, progress: dict | None = None) -> dict:
    progress = progress or json.loads(PROGRESS.read_text(encoding="utf-8"))
    head_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    acceptance_revision = progress.get("acceptance_revision")
    spec_revision = progress.get("spec_revision")
    report = {
        "schema_version": "ci-stage-gate/v1",
        "spec_revision": spec_revision,
        "acceptance_revision": acceptance_revision,
        "stage": stage,
        "command": ["python", "scripts/ci/ci_stage_gate.py", "--stage", stage],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gate_head_sha": head_sha,
        "checks": [],
    }
    registry = json.loads((ROOT / "docs/specs/registry.yaml").read_text(encoding="utf-8"))
    configured_tests = registry["directions"]["ci"]["gate"]["tests"].get(stage, [])
    if configured_tests:
        test = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *configured_tests],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        report["checks"].append({
            "id": "focused-tests",
            "status": "passed" if test.returncode == 0 else "failed",
            "command": [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *configured_tests],
            "exit_code": test.returncode,
            "stdout": test.stdout[-10000:],
            "stderr": test.stderr[-3000:],
        })
    else:
        report["checks"].append({"id": "focused-tests", "status": "blocked", "reason": "no focused tests are configured for this stage"})
    if stage == "Phase 0":
        snapshot_id = progress.get("phase0_snapshot_id")
        report["snapshot_id"] = snapshot_id
        snapshot_result = verify_snapshot(snapshot_id or "", spec_revision)
        report["checks"].append({"id": "immutable-snapshot-integrity", **snapshot_result})
        stage_data = progress["stages"][stage]
        corpus_baseline = ROOT / "src/react_agent/apps/docs_troubleshoot/git_docs_corpus_baseline.json"
        snapshots_root = (ROOT / "docs/specs/ci/evidence/snapshots").resolve()
        corpus_separate = corpus_baseline.is_file() and not corpus_baseline.resolve().is_relative_to(snapshots_root)
        report["checks"].append({
            "id": "docs-corpus-baseline-separation",
            "status": "passed" if corpus_separate else "failed",
            "path": corpus_baseline.relative_to(ROOT).as_posix(),
        })
        review = next(
            (item for item in stage_data.get("acceptance", []) if item.get("id") == "CI-P0-4-v2"),
            {},
        )
        missing_review = [path for path in review.get("evidence", []) if not (ROOT / path).is_file()]
        review_passed = review.get("status") == "complete" and not missing_review
        report["checks"].append({
            "id": "phase0-independent-review",
            "status": "passed" if review_passed else "blocked",
            "acceptance_status": review.get("status"),
            "missing_evidence": missing_review,
        })
        technical_passed = (
            snapshot_result["status"] == "passed"
            and report["checks"][0].get("status") == "passed"
            and corpus_separate
        )
        report["status"] = "passed" if technical_passed and review_passed else "blocked"
    elif stage == "Phase 1":
        errors = validate_registry()
        report["checks"].append(
            {
                "id": "registry-v2-semantic-validation",
                "status": "passed" if not errors else "failed",
                "errors": errors,
            }
        )
        sample_id = progress.get("selector_sample_id")
        sample_path = ROOT / "docs/specs/ci/evidence/selector-samples" / f"{sample_id}.json" if sample_id else None
        backtest_path = progress.get("selector_backtest_report")
        backtest_path = ROOT / backtest_path if backtest_path else None
        sample_ok = bool(sample_path and sample_path.is_file())
        report["selector_sample_id"] = sample_id
        report["checks"].append({"id": "selector-fixed-sample", "status": "passed" if sample_ok else "blocked", "path": sample_path.relative_to(ROOT).as_posix() if sample_ok else None})
        if backtest_path and backtest_path.exists():
            backtest = json.loads(backtest_path.read_text(encoding="utf-8"))
            sample = json.loads(sample_path.read_text(encoding="utf-8")) if sample_ok else {}
            valid_backtest = (
                backtest.get("sample_id") == sample_id
                and backtest.get("spec_revision") == spec_revision
                and backtest.get("source_sha") == sample.get("source_sha")
                and backtest.get("source_sha256") == hashlib.sha256(sample_path.read_bytes()).hexdigest()
                and backtest.get("registry_sha256") == hashlib.sha256((ROOT / "docs/specs/ci/registry-v2.json").read_bytes()).hexdigest()
                and backtest.get("metrics", {}).get("false_positive_rules") is None
                and backtest.get("metrics", {}).get("missed_expected_rules") is None
                and backtest.get("sample_size") == 100
            ) if sample_ok else False
            replay_passed = valid_backtest and backtest.get("conclusion") == "pass"
            report["checks"].append({"id": "selector-backtest", "status": "passed" if replay_passed else "blocked" if valid_backtest else "failed", "metrics": backtest.get("metrics"), "conclusion": backtest.get("conclusion"), "source_sha256": backtest.get("source_sha256")})
        else:
            report["checks"].append({"id": "selector-backtest", "status": "failed", "reason": "backtest evidence missing"})
        selector = select(["src/react_agent/harness/contracts/__init__.py", "docs/specs/ci/spec.md", "unmapped/example.xyz"])
        report["checks"].append(
            {
                "id": "selector-fail-closed",
                "status": "passed" if selector["status"] == "blocked" and selector["unmapped_paths"] else "failed",
                "result": selector,
            }
        )
        r9_status = next((item.get("status") for item in progress["stages"][stage].get("acceptance", []) if item.get("id") == "CI-P1-3"), "blocked")
        report["checks"].append({"id": "r9-execution-acceptance", "status": "blocked" if r9_status != "complete" else "passed", "reason": "Fork secret isolation and effective runtime permissions require an isolated GitHub Actions run."})
        fail_closed_ok = selector["status"] == "blocked" and bool(selector["unmapped_paths"])
        replay_check = next(item for item in report["checks"] if item["id"] == "selector-backtest")
        report["status"] = "passed" if not errors and fail_closed_ok and sample_ok and replay_check["status"] == "passed" and r9_status == "complete" else "blocked"
    else:
        report["status"] = "blocked"
        report["reason"] = f"{stage} is not implemented; no pass conclusion is available."
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True, choices=[f"Phase {n}" for n in range(6)])
    args = parser.parse_args()
    report = run(args.stage)
    test_failures = [item for item in report["checks"] if item["status"] in {"failed", "blocked"}]
    if test_failures and report["status"] == "passed":
        report["status"] = "blocked"
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = REPORT_DIR / f"{args.stage.lower().replace(' ', '-')}-{timestamp}-{report['gate_head_sha'][:8]}.json"
    if target.exists():
        raise SystemExit(f"refusing to overwrite gate report: {target}")
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    target.write_text(encoded, encoding="utf-8")
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    progress = json.loads(PROGRESS.read_text(encoding="utf-8"))
    progress["updated_at"] = datetime.now(timezone.utc).isoformat()
    progress["stages"][args.stage]["last_gate"] = {
        "status": report["status"],
        "report": target.relative_to(ROOT).as_posix(),
        "report_sha256": digest,
        "spec_revision": report.get("spec_revision"),
        "acceptance_revision": report.get("acceptance_revision"),
        "snapshot_id": report.get("snapshot_id") or report.get("selector_sample_id"),
    }
    progress["last_gate"] = {"stage": args.stage, **progress["stages"][args.stage]["last_gate"]}
    PROGRESS.write_text(json.dumps(progress, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"stage": args.stage, "status": report["status"], "report": target.relative_to(ROOT).as_posix(), "sha256": digest}, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
