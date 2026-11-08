"""Run the bounded CI subsystem stage gate and persist a report."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

if __package__:
    from . import audit_workflow_security, r9_runtime_probe
    from .hash_utils import canonical_bytes, sha256_file
    from .registry_v2 import ROOT, select, validate_registry
else:
    import audit_workflow_security
    import r9_runtime_probe
    from hash_utils import canonical_bytes, sha256_file
    from registry_v2 import ROOT, select, validate_registry

REPORT_DIR = ROOT / "artifacts/ci/stage-gates"
PROGRESS = ROOT / "docs/specs/ci/progress.yaml"


def test_environment() -> dict[str, str]:
    """Run focused tests with the repository source tree and test-dir policy."""
    env = dict(os.environ)
    source_path = str((ROOT / "src").resolve())
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (source_path, existing)))
    env["REACT_AGENT_PERMISSIVE_TEST_DIRS"] = "1"
    return env


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
    if source_hash != sha256_file(baseline_path):
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
        digest = sha256_file(artifact_path)
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


def validate_selector_backtest(
    backtest: dict, sample: dict, sample_id: str, sample_path: Path, spec_revision: str
) -> bool:
    """Validate replay provenance and metrics without requiring zero unmapped paths."""
    metrics = backtest.get("metrics", {})
    if not isinstance(metrics, dict):
        return False
    changed = metrics.get("changed_files")
    mapped = metrics.get("mapped_files")
    unmapped = metrics.get("unmapped_files")
    excluded = metrics.get("excluded_files", 0)
    coverage = metrics.get("mapped_coverage")
    counts_valid = (
        isinstance(changed, int)
        and not isinstance(changed, bool)
        and isinstance(mapped, int)
        and not isinstance(mapped, bool)
        and isinstance(unmapped, int)
        and not isinstance(unmapped, bool)
        and isinstance(excluded, int)
        and not isinstance(excluded, bool)
        and changed == mapped + unmapped + excluded
        and (coverage is None if changed == 0 else isinstance(coverage, (int, float)) and round((mapped + excluded) / changed, 4) == coverage)
    )
    rows = backtest.get("samples")
    row_counts_valid = (
        isinstance(rows, list)
        and len(rows) == 100
        and all(
            isinstance(row, dict)
            and isinstance(row.get("changed_files"), int)
            and not isinstance(row.get("changed_files"), bool)
            and isinstance(row.get("unmapped_paths"), list)
            and isinstance(row.get("excluded_paths", []), list)
            for row in rows
        )
        and sum(row["changed_files"] for row in rows) == changed
        and sum(len(row["unmapped_paths"]) for row in rows) == unmapped
        and sum(len(row.get("excluded_paths", [])) for row in rows) == excluded
    )
    registry_validation = backtest.get("registry_validation", {})
    if not isinstance(registry_validation, dict):
        return False
    registry_ok = registry_validation.get("status") == "pass" and not registry_validation.get("errors")
    expected_conclusion = "pass" if registry_ok and unmapped == 0 else "blocked"
    return bool(
        backtest.get("sample_id") == sample_id
        and backtest.get("schema_version") == "ci-selector-backtest/v2"
        and backtest.get("spec_revision") == spec_revision
        and backtest.get("source_sha") == sample.get("source_sha")
        and backtest.get("source_sha256") == sha256_file(sample_path)
        and backtest.get("registry_sha256") == sha256_file(ROOT / "docs/specs/ci/registry-v2.json")
        and backtest.get("sample_size") == 100
        and counts_valid
        and row_counts_valid
        and registry_ok
        and metrics.get("false_positive_rules") is None
        and metrics.get("missed_expected_rules") is None
        and backtest.get("conclusion") == expected_conclusion
    )


def validate_rule_level_backtest(
    backtest: dict,
    labels: dict,
    sample: dict,
    sample_id: str,
    sample_path: Path,
    labels_path: Path,
    spec_revision: str,
) -> bool:
    """Validate independent Registry rule labels and their replay provenance."""

    metrics = backtest.get("metrics")
    rows = backtest.get("samples")
    label_rows = labels.get("rows")
    if not isinstance(metrics, dict) or not isinstance(rows, list) or not isinstance(label_rows, list):
        return False
    if labels.get("schema_version") != "ci-selector-expected-rules/v1":
        return False
    if labels.get("label_set_is_independent_of_registry") is not True:
        return False
    if backtest.get("schema_version") != "ci-selector-rule-backtest/v1":
        return False
    if backtest.get("sample_id") != sample_id or labels.get("sample_id") != sample_id:
        return False
    if backtest.get("spec_revision") != spec_revision:
        return False
    if backtest.get("source_sha") != sample.get("source_sha"):
        return False
    if backtest.get("source_sample_sha256") != sha256_file(sample_path):
        return False
    if backtest.get("expected_labels_sha256") != sha256_file(labels_path):
        return False
    if backtest.get("registry_sha256") != sha256_file(ROOT / "docs/specs/ci/registry-v2.json"):
        return False
    if len(rows) != 100 or len(label_rows) != 100:
        return False
    row_count = sum(row.get("changed_files", 0) for row in rows if isinstance(row, dict))
    unmapped_count = sum(len(row.get("unmapped_paths", [])) for row in rows if isinstance(row, dict))
    excluded_count = sum(len(row.get("excluded_paths", [])) for row in rows if isinstance(row, dict))
    comparable_count = sum(row.get("comparison_status") == "comparable" for row in rows if isinstance(row, dict))
    expected_metrics = {
        "changed_files": row_count,
        "unmapped_files": unmapped_count,
        "excluded_files": excluded_count,
        "comparable_rows": comparable_count,
        "unmeasured_rows": len(rows) - comparable_count,
        "measurement_status": "complete" if comparable_count == len(rows) else "partial",
    }
    if any(metrics.get(key) != value for key, value in expected_metrics.items()):
        return False
    if not isinstance(metrics.get("false_positive_rules"), list) or not isinstance(metrics.get("missed_expected_rules"), list):
        return False
    expected_conclusion = "pass" if (
        metrics["measurement_status"] == "complete"
        and unmapped_count == 0
        and not metrics["false_positive_rules"]
        and not metrics["missed_expected_rules"]
    ) else "blocked"
    return backtest.get("conclusion") == expected_conclusion


def run(
    stage: str,
    progress: dict | None = None,
    *,
    r9_runtime_evidence: Path | None = None,
    expected_head_sha: str | None = None,
    expected_base_sha: str | None = None,
) -> dict:
    progress = progress or json.loads(PROGRESS.read_text(encoding="utf-8"))
    actual_head_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    head_sha = expected_head_sha or actual_head_sha
    if not re.fullmatch(r"[0-9a-f]{40}", head_sha):
        raise ValueError("expected head SHA must be a 40-character commit SHA")
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
    if expected_head_sha is not None:
        report["checks"].append({
            "id": "expected-head-checkout-binding",
            "status": "passed" if actual_head_sha == expected_head_sha else "failed",
            "actual_head_sha": actual_head_sha,
            "expected_head_sha": expected_head_sha,
        })
    registry = json.loads((ROOT / "docs/specs/registry.yaml").read_text(encoding="utf-8"))
    configured_tests = registry["directions"]["ci"]["gate"]["tests"].get(stage, [])
    if configured_tests:
        test = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *configured_tests],
            cwd=ROOT,
            env=test_environment(),
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
        review_report = {}
        if review_passed and review.get("evidence"):
            try:
                review_text = (ROOT / review["evidence"][0]).read_text(encoding="utf-8")
                conclusion_match = re.search(r"(?im)^\s*(?:#+\s*)?(?:[-*]\s*)?(?:Conclusion|结论)\s*[:：]\s*`?([A-Za-z_]+)", review_text)
                review_report = {"conclusion": conclusion_match.group(1) if conclusion_match else None}
            except OSError:
                review_report = {}
        report["checks"].append({
            "id": "phase0-independent-review",
            "status": "passed" if review_passed else "blocked",
            "acceptance_status": review.get("status"),
            "missing_evidence": missing_review,
        })
        review_conclusion = review_report.get("conclusion")
        review_conclusion_passed = review_conclusion == "Complete"
        report["checks"].append({
            "id": "phase0-review-conclusion",
            "status": "passed" if review_conclusion_passed else "blocked",
            "conclusion": review_conclusion,
            "reason": None if review_conclusion_passed else "independent review did not conclude Complete",
        })
        technical_passed = (
            snapshot_result["status"] == "passed"
            and report["checks"][0].get("status") == "passed"
            and corpus_separate
        )
        report["status"] = "passed" if technical_passed and review_passed and review_conclusion_passed else "blocked"
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
            valid_backtest = validate_selector_backtest(backtest, sample, sample_id, sample_path, spec_revision) if sample_ok and isinstance(backtest, dict) else False
            # A fixed replay can be valid evidence while remaining ineligible
            # for a subset gate because unmapped paths or missing labels exist.
            # Keep those two decisions separate: Phase 1 accepts the evidence
            # contract, while later phases decide whether subset gating is safe.
            replay_evidence_passed = valid_backtest
            report["checks"].append({
                "id": "selector-backtest",
                "status": "passed" if replay_evidence_passed else "failed",
                "evidence_status": "valid" if replay_evidence_passed else "invalid",
                "gate_eligibility": "eligible" if backtest.get("conclusion") == "pass" else "blocked",
                "metrics": backtest.get("metrics"),
                "conclusion": backtest.get("conclusion"),
                "source_sha256": backtest.get("source_sha256"),
            })
        else:
            report["checks"].append({"id": "selector-backtest", "status": "failed", "reason": "backtest evidence missing"})
        labels_path_value = progress.get("selector_rule_labels")
        rule_backtest_path_value = progress.get("selector_rule_backtest_report")
        labels_path = ROOT / labels_path_value if labels_path_value else None
        rule_backtest_path = ROOT / rule_backtest_path_value if rule_backtest_path_value else None
        labels_ok = bool(labels_path and labels_path.is_file())
        report["checks"].append({
            "id": "selector-rule-labels",
            "status": "passed" if labels_ok else "blocked",
            "path": labels_path.relative_to(ROOT).as_posix() if labels_ok else None,
        })
        rule_backtest_ok = False
        if labels_ok and rule_backtest_path and rule_backtest_path.is_file() and sample_ok:
            try:
                labels = json.loads(labels_path.read_text(encoding="utf-8"))
                rule_backtest = json.loads(rule_backtest_path.read_text(encoding="utf-8"))
                sample = json.loads(sample_path.read_text(encoding="utf-8"))
                rule_backtest_ok = validate_rule_level_backtest(
                    rule_backtest,
                    labels,
                    sample,
                    sample_id,
                    sample_path,
                    labels_path,
                    spec_revision,
                )
                report["checks"].append({
                    "id": "selector-rule-level-backtest",
                    "status": "passed" if rule_backtest_ok else "failed",
                    "evidence_status": "valid" if rule_backtest_ok else "invalid",
                    "path": rule_backtest_path.relative_to(ROOT).as_posix(),
                    "metrics": rule_backtest.get("metrics"),
                    "conclusion": rule_backtest.get("conclusion"),
                })
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                report["checks"].append({"id": "selector-rule-level-backtest", "status": "failed", "reason": "rule-level evidence is unreadable"})
        else:
            report["checks"].append({"id": "selector-rule-level-backtest", "status": "blocked", "reason": "independent labels or rule-level backtest evidence is missing"})
        selector = select(["src/react_agent/harness/contracts/__init__.py", "docs/specs/ci/spec.md", "unmapped/example.xyz"])
        report["checks"].append(
            {
                "id": "selector-fail-closed",
                "status": "passed" if selector["status"] == "blocked" and selector["unmapped_paths"] else "failed",
                "result": selector,
            }
        )
        r9_acceptance = next((item for item in progress["stages"][stage].get("acceptance", []) if item.get("id") == "CI-P1-3"), {})
        r9_status = r9_acceptance.get("status", "blocked")
        security_snapshot = audit_workflow_security.audit()
        security_findings = security_snapshot.get("findings", [])
        report["checks"].append({
            "id": "r9-static-security-audit",
            "status": "passed" if not security_findings else "failed",
            "head_sha": security_snapshot["head_sha"],
            "finding_count": len(security_findings),
            "findings": security_findings,
        })
        r9_evidence_path = next(
            (ROOT / path for path in r9_acceptance.get("evidence", []) if path.endswith("phase1-r9-acceptance.json")),
            None,
        )
        try:
            r9_evidence = json.loads(r9_evidence_path.read_text(encoding="utf-8")) if r9_evidence_path else {}
        except (OSError, json.JSONDecodeError):
            r9_evidence = {}
        if not isinstance(r9_evidence, dict):
            r9_evidence = {}
        runtime = r9_evidence.get("runtime_acceptance", {})
        if not isinstance(runtime, dict):
            runtime = {}
        runtime_validation = None
        evidence_path = r9_evidence_path
        if r9_runtime_evidence is not None:
            evidence_path = r9_runtime_evidence
            try:
                probe_report = json.loads(r9_runtime_evidence.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                probe_report = {}
            runtime_validation = r9_runtime_probe.validate_report(
                probe_report if isinstance(probe_report, dict) else {},
                expected_head_sha=head_sha,
                expected_base_sha=expected_base_sha or "",
            )
            r9_runtime_passed = runtime_validation["status"] == "passed"
        else:
            r9_runtime_passed = (
                r9_status == "complete"
                and r9_evidence.get("schema_version") == "ci-r9-acceptance/v1"
                and r9_evidence.get("head_sha") == head_sha
                and r9_evidence.get("findings_remain") is False
                and runtime.get("status") == "passed"
            )
        report["checks"].append({
            "id": "r9-execution-acceptance",
            "status": "passed" if r9_runtime_passed and not security_findings else "blocked",
            "evidence_path": evidence_path.as_posix() if evidence_path else None,
            "evidence_head_sha": runtime_validation["head_sha"] if runtime_validation else r9_evidence.get("head_sha"),
            "runtime_status": runtime_validation["status"] if runtime_validation else runtime.get("status"),
            "runtime_validation_errors": runtime_validation["errors"] if runtime_validation else [],
            "reason": None if r9_runtime_passed else "Current-head isolated GitHub Actions evidence for fork Secret isolation and effective permissions is missing or incomplete.",
        })
        fail_closed_ok = selector["status"] == "blocked" and bool(selector["unmapped_paths"])
        replay_check = next(item for item in report["checks"] if item["id"] == "selector-backtest")
        rule_replay_check = next(item for item in report["checks"] if item["id"] == "selector-rule-level-backtest")
        static_audit = next(item for item in report["checks"] if item["id"] == "r9-static-security-audit")
        runtime_check = next(item for item in report["checks"] if item["id"] == "r9-execution-acceptance")
        report["status"] = "passed" if not errors and fail_closed_ok and sample_ok and replay_check["status"] == "passed" and rule_replay_check["status"] == "passed" and static_audit["status"] == "passed" and runtime_check["status"] == "passed" else "blocked"
    elif stage == "Phase 2":
        observation_path = ROOT / "docs/specs/ci/evidence/phase2-shadow-observation.md"
        observation_text = observation_path.read_text(encoding="utf-8") if observation_path.is_file() else ""
        contract_paths = [
            ROOT / "scripts/ci/aggregate_shadow_observation.py",
            ROOT / "scripts/ci/expected_pr_checks.py",
            ROOT / "tests/test_shadow_observation.py",
        ]
        contract_ok = all(path.is_file() for path in contract_paths)
        report["checks"].append({
            "id": "shadow-aggregation-contract",
            "status": "passed" if contract_ok else "blocked",
            "evidence": [path.relative_to(ROOT).as_posix() for path in contract_paths if path.is_file()],
        })
        report["checks"].append({
            "id": "shadow-observation-window",
            "status": "blocked",
            "evidence": observation_path.relative_to(ROOT).as_posix() if observation_path.is_file() else None,
            "reason": "The live 14-day observation window is not complete; report-only evidence cannot authorize a subset gate.",
        })
        report["status"] = "blocked"
    else:
        report["status"] = "blocked"
        report["reason"] = f"{stage} is not implemented; no pass conclusion is available."
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True, choices=[f"Phase {n}" for n in range(6)])
    parser.add_argument("--r9-runtime-evidence", type=Path)
    parser.add_argument("--expected-head-sha")
    parser.add_argument("--expected-base-sha")
    args = parser.parse_args()
    report = run(
        args.stage,
        r9_runtime_evidence=args.r9_runtime_evidence,
        expected_head_sha=args.expected_head_sha,
        expected_base_sha=args.expected_base_sha,
    )
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
    # Hash the bytes as persisted on disk after platform newline handling.
    # The progress source must reproduce this digest on Windows and POSIX.
    digest = sha256_file(target)
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
