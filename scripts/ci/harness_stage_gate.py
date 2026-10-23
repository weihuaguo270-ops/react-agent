"""Run a Harness phase gate and persist its result in progress.yaml.

progress.yaml uses the JSON subset of YAML so the gate needs no extra parser.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROGRESS = ROOT / "progress.yaml"
REPORT_DIR = ROOT / "artifacts" / "harness" / "stage-gates"
SPEC_ANALYZER = ROOT / ".codex" / "skills" / "spec-progress-workflow" / "scripts" / "spec_workflow.py"
PHASE_TESTS = {
    "P0": ["tests/test_harness_schema.py", "tests/test_harness_reliability.py"],
    "P1": ["tests/evaluation/test_harness_contracts.py", "tests/evaluation/test_harness_schema.py"],
    "P2": [
        "tests/evaluation/test_harness_contracts.py", "tests/test_harness_r2.py",
        "tests/test_harness_r3.py", "tests/test_mcp_mock.py", "tests/test_mcp_stdio_contract.py",
        "tests/test_structured_output_contract.py", "tests/test_deterministic_replay.py",
        "tests/test_runtime_observability.py", "tests/evaluation/test_http_trajectory_contract.py",
        "tests/test_shared_idempotency.py",
    ],
    "P3": ["tests/evaluation/test_harness_contracts.py", "tests/test_harness_schema.py"],
    "P4": [
        "tests/harness/test_deterministic_replay.py", "tests/test_harness_closed_loop_decision.py",
        "tests/test_failure_regression_gate.py", "tests/test_run_step_watcher_evidence.py",
    ],
    "P5": ["tests/evaluation/test_harness_contracts.py", "tests/test_harness_schema.py"],
}


def load_progress() -> dict:
    return json.loads(PROGRESS.read_text(encoding="utf-8"))


def resolve_repo_path(relative: str) -> Path:
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(ROOT.resolve()):
        raise ValueError(f"evidence path escapes repository: {relative}")
    return path


def check_evidence(requirements: list[dict]) -> list[dict]:
    results = []
    for requirement in requirements:
        path = resolve_repo_path(requirement["path"])
        passed = path.is_file()
        detail = "present" if passed else "missing"
        assertion = requirement.get("json_assertion")
        if passed and assertion:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                passed = all(payload.get(key) == value for key, value in assertion.items())
                detail = "JSON assertions passed" if passed else "JSON assertion mismatch"
            except (OSError, json.JSONDecodeError) as exc:
                passed, detail = False, f"invalid JSON: {exc}"
        results.append({"id": requirement["id"], "path": requirement["path"], "passed": passed, "detail": detail})
    return results


def check_acceptance_evidence(items: list[dict]) -> list[dict]:
    results = []
    for item in items:
        paths = item.get("evidence", [])
        missing = [relative for relative in paths if not resolve_repo_path(relative).exists()]
        artifact_hashes = []
        for artifact in item.get("artifacts", []):
            path = resolve_repo_path(artifact["path"])
            actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
            expected = artifact.get("sha256")
            artifact_hashes.append({
                "path": artifact["path"],
                "expected": expected,
                "actual": actual,
                "passed": actual is not None and actual == expected,
            })
        results.append({
            "id": item["id"], "status": item["status"],
            "passed": not missing and all(check["passed"] for check in artifact_hashes),
            "missing": missing,
            "artifact_hashes": artifact_hashes,
        })
    return results


def check_spec_consistency() -> dict | None:
    command = [sys.executable, str(SPEC_ANALYZER), "analyze", "--direction", "harness"]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        print(f"Invalid Spec consistency report: {exc}", file=sys.stderr)
        return None


def stage_status_after_gate(gate_passed: bool, spec_status: str | None) -> str:
    if gate_passed and spec_status not in {
        "partial", "in progress", "proposed", "not started",
    }:
        return "complete"
    return "in_progress"


def persist_report(report_path: Path, report_bytes: bytes) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_bytes(report_bytes)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, choices=tuple(PHASE_TESTS))
    args = parser.parse_args()
    consistency = check_spec_consistency()
    if not consistency:
        print("Spec consistency check failed; stage gate was not run and progress was not updated.", file=sys.stderr)
        return 2
    spec_status = consistency.get("spec_phase_status", {}).get(args.stage)
    progress = load_progress()
    stage = progress["stages"][args.stage]
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *PHASE_TESTS[args.stage]]
    env = dict(__import__("os").environ)
    env["REACT_AGENT_PERMISSIVE_TEST_DIRS"] = "1"
    test = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True, check=False)
    cross_repo_command = None
    cross_repo_test = None
    cross_repo_report = None
    cross_repo_passed = args.stage != "P4"
    if args.stage == "P4":
        cross_repo_command = [
            sys.executable, str(ROOT / "scripts" / "eval" / "failure" / "run_step_watcher_evidence.py"),
        ]
        cross_repo_test = subprocess.run(
            cross_repo_command, cwd=ROOT, env=env, text=True, capture_output=True, check=False,
        )
        try:
            cross_repo_report = json.loads(cross_repo_test.stdout)
        except json.JSONDecodeError:
            cross_repo_report = None
        cross_repo_passed = (
            cross_repo_test.returncode == 0
            and isinstance(cross_repo_report, dict)
            and cross_repo_report.get("n_scenarios", 0) > 0
            and cross_repo_report.get("n_passed") == cross_repo_report.get("n_scenarios")
            and cross_repo_report.get("golden_suite_pass_rate") == 1.0
            and cross_repo_report.get("golden_suite_exit_code") == 0
        )
    evidence = check_evidence(stage.get("required_evidence", []))
    acceptance_evidence = check_acceptance_evidence(stage["acceptance"])
    pending = [item["id"] for item in stage["acceptance"] if item["status"] != "complete"]
    missing_acceptance_evidence = [item["id"] for item in acceptance_evidence if not item["passed"]]
    passed = (
        test.returncode == 0 and all(item["passed"] for item in evidence)
        and not pending and not missing_acceptance_evidence and cross_repo_passed
    )
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
                              capture_output=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        head = "unknown"
    report = {
        "schema_version": "harness-stage-gate/v1", "stage": args.stage,
        "timestamp": datetime.now(timezone.utc).isoformat(), "head": head,
        "spec_status": spec_status,
        "command": command, "test_exit_code": test.returncode,
        "test_stdout": test.stdout[-12000:], "test_stderr": test.stderr[-4000:],
        "cross_repo_command": cross_repo_command,
        "cross_repo_test_exit_code": cross_repo_test.returncode if cross_repo_test else None,
        "cross_repo_stdout": cross_repo_test.stdout[-12000:] if cross_repo_test else None,
        "cross_repo_stderr": cross_repo_test.stderr[-4000:] if cross_repo_test else None,
        "cross_repo_passed": cross_repo_passed,
        "required_evidence": evidence, "acceptance_evidence": acceptance_evidence,
        "acceptance_pending": pending, "passed": passed,
    }
    stage["status"] = stage_status_after_gate(passed, spec_status)
    report["stage_status"] = stage["status"]
    report_path = REPORT_DIR / f"{args.stage.lower()}-latest.json"
    report_bytes = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    persist_report(report_path, report_bytes)
    stage["last_gate"] = {
        "status": "passed" if passed else "failed",
        "report": report_path.relative_to(ROOT).as_posix(),
        "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
    }
    progress["updated_at"] = datetime.now(timezone.utc).isoformat()
    progress["last_gate"] = {"stage": args.stage, **stage["last_gate"]}
    PROGRESS.write_text(json.dumps(progress, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(test.stdout, end="")
    if test.stderr:
        print(test.stderr, file=sys.stderr, end="")
    if args.stage == "P4":
        print(f"cross_repo_golden={'PASS' if cross_repo_passed else 'FAIL'}")
        if cross_repo_test and not cross_repo_passed:
            print(cross_repo_test.stdout[-4000:], end="")
            if cross_repo_test.stderr:
                print(cross_repo_test.stderr[-2000:], file=sys.stderr, end="")
    print(f"stage={args.stage} status={stage['status']}")
    print(f"report={report_path.relative_to(ROOT).as_posix()}")
    print(f"report_sha256={stage['last_gate']['report_sha256']}")
    for item in evidence:
        print(f"evidence[{item['id']}]={'PASS' if item['passed'] else 'MISSING'} {item['path']}")
    for item in acceptance_evidence:
        if item["missing"]:
            print(f"acceptance_evidence[{item['id']}]=MISSING {','.join(item['missing'])}")
    if pending:
        print("acceptance_pending=" + ",".join(pending))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
