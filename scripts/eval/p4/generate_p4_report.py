"""Generate P4 acceptance report aggregating all evidence."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]


def compute_sha256(file_path: Path) -> str:
    """Compute SHA256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def generate_p4_report(output_path: Path | None = None) -> dict[str, Any]:
    """Generate P4 acceptance report.

    Aggregates:
    - Baseline compare results
    - Repair/reverify closure evidence
    - All artifact SHA256 hashes
    - Evidence classification

    Args:
        output_path: Optional path to write report JSON

    Returns:
        P4 acceptance report
    """
    artifacts_root = ROOT / "artifacts"
    harness_dir = artifacts_root / "harness"
    repair_dir = artifacts_root / "software-delivery" / "repair_then_pass"

    # Initialize report
    report = {
        "schema_version": "p4-acceptance/v1",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "baseline_compare": _get_baseline_compare_status(harness_dir),
        "repair_reverify_closure": _get_repair_closure_status(repair_dir),
        "evidence_classification": _classify_evidence(repair_dir),
        "artifacts": _collect_artifact_hashes(repair_dir, harness_dir),
        "summary": {},
    }

    # Generate summary
    report["summary"] = {
        "all_requirements_met": _check_all_requirements(report),
        "baseline_compare_exists": report["baseline_compare"]["exists"],
        "repair_reverify_traceable": report["repair_reverify_closure"]["traceable"],
        "artifacts_validated": len(report["artifacts"]) > 0,
    }

    # Write report if output path provided
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8"
        )

    return report


def _get_baseline_compare_status(harness_dir: Path) -> dict[str, Any]:
    """Get baseline compare report status."""
    baseline_compare_path = harness_dir / "baseline-compare-latest.json"

    # Ensure harness_dir exists
    if not harness_dir.exists():
        harness_dir.mkdir(parents=True, exist_ok=True)

    if not baseline_compare_path.exists():
        return {
            "exists": False,
            "path": str(baseline_compare_path),
            "status": "missing",
        }

    try:
        data = json.loads(baseline_compare_path.read_text(encoding="utf-8"))
        return {
            "exists": True,
            "path": str(baseline_compare_path),
            "sha256": compute_sha256(baseline_compare_path),
            "status": data.get("summary", {}).get("status", "unknown"),
        }
    except Exception as e:
        return {
            "exists": True,
            "path": str(baseline_compare_path),
            "status": "error",
            "error": str(e),
        }


def _get_repair_closure_status(repair_dir: Path) -> dict[str, Any]:
    """Get repair/reverify closure status."""
    acceptance_path = repair_dir / "acceptance.json"

    if not repair_dir.exists() or not acceptance_path.exists():
        return {
            "traceable": False,
            "evidence_path": str(repair_dir),
            "status": "missing",
        }

    try:
        acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
        return {
            "traceable": True,
            "evidence_path": str(repair_dir),
            "acceptance": str(acceptance_path),
            "sha256": compute_sha256(acceptance_path),
            "reverified": acceptance.get("reverified", False),
            "status": "passed" if acceptance.get("reverified") else "incomplete",
        }
    except Exception as e:
        return {
            "traceable": False,
            "evidence_path": str(repair_dir),
            "status": "error",
            "error": str(e),
        }


def _classify_evidence(repair_dir: Path) -> dict[str, list[str]]:
    """Classify evidence into historical, fixture, and executed."""
    if not repair_dir.exists():
        return {
            "historical_evidence": [],
            "fixture_evidence": [],
            "executed": [],
        }

    acceptance_path = repair_dir / "acceptance.json"
    task_path = repair_dir / "task.json"

    classification = {
        "historical_evidence": [],
        "fixture_evidence": [],
        "executed": [],
    }

    # Check if evidence is from historical collection or fresh execution
    if task_path.exists():
        task_data = json.loads(task_path.read_text(encoding="utf-8"))
        evidence_kind = task_data.get("evidence_kind", "")

        if "historical" in evidence_kind:
            classification["historical_evidence"].append(str(task_path))
        else:
            classification["executed"].append(str(task_path))

    if acceptance_path.exists():
        acceptance_data = json.loads(acceptance_path.read_text(encoding="utf-8"))

        if acceptance_data.get("reverified"):
            classification["executed"].append(str(acceptance_path))
        else:
            classification["historical_evidence"].append(str(acceptance_path))

    # Fixture evidence (baseline, test assets)
    for subdir in ["before", "after", "repair"]:
        subdir_path = repair_dir / subdir
        if subdir_path.exists():
            classification["fixture_evidence"].append(str(subdir_path))

    return classification


def _collect_artifact_hashes(repair_dir: Path, harness_dir: Path) -> list[dict[str, str]]:
    """Collect SHA256 hashes of all artifacts."""
    artifacts = []

    # Repair evidence artifacts
    if repair_dir.exists():
        for artifact_name in ["acceptance.json", "task.json"]:
            artifact_path = repair_dir / artifact_name
            if artifact_path.exists():
                artifacts.append({
                    "path": str(artifact_path.relative_to(ROOT)),
                    "sha256": compute_sha256(artifact_path),
                })

    # Baseline compare artifact
    baseline_compare = harness_dir / "baseline-compare-latest.json"
    if baseline_compare.exists():
        artifacts.append({
            "path": str(baseline_compare.relative_to(ROOT)),
            "sha256": compute_sha256(baseline_compare),
        })

    return artifacts


def _check_all_requirements(report: dict) -> bool:
    """Check if all P4-1 requirements are met."""
    baseline_ok = report["baseline_compare"]["exists"]
    repair_ok = report["repair_reverify_closure"]["traceable"]
    reverified = report["repair_reverify_closure"].get("reverified", False)
    artifacts_ok = len(report["artifacts"]) > 0

    return baseline_ok and repair_ok and reverified and artifacts_ok


if __name__ == "__main__":
    # Generate P4 report
    output_path = ROOT / "artifacts" / "harness" / "p4-acceptance-report.json"
    report = generate_p4_report(output_path)

    print(f"P4 Acceptance Report generated: {output_path}")
    print(f"Summary: {json.dumps(report['summary'], indent=2)}")
