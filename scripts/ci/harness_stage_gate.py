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
        "tests/test_deterministic_replay.py", "tests/test_harness_closed_loop_decision.py",
        "tests/test_failure_regression_gate.py",
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
        results.append({
            "id": item["id"], "status": item["status"],
            "passed": not missing, "missing": missing,
        })
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, choices=tuple(PHASE_TESTS))
    args = parser.parse_args()
    progress = load_progress()
    stage = progress["stages"][args.stage]
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *PHASE_TESTS[args.stage]]
    env = dict(__import__("os").environ)
    env["REACT_AGENT_PERMISSIVE_TEST_DIRS"] = "1"
    test = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True, check=False)
    evidence = check_evidence(stage.get("required_evidence", []))
    acceptance_evidence = check_acceptance_evidence(stage["acceptance"])
    pending = [item["id"] for item in stage["acceptance"] if item["status"] != "complete"]
    missing_acceptance_evidence = [item["id"] for item in acceptance_evidence if not item["passed"]]
    passed = (
        test.returncode == 0 and all(item["passed"] for item in evidence)
        and not pending and not missing_acceptance_evidence
    )
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
                              capture_output=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        head = "unknown"
    report = {
        "schema_version": "harness-stage-gate/v1", "stage": args.stage,
        "timestamp": datetime.now(timezone.utc).isoformat(), "head": head,
        "command": command, "test_exit_code": test.returncode,
        "test_stdout": test.stdout[-12000:], "test_stderr": test.stderr[-4000:],
        "required_evidence": evidence, "acceptance_evidence": acceptance_evidence,
        "acceptance_pending": pending, "passed": passed,
    }
    report_path = REPORT_DIR / f"{args.stage.lower()}-latest.json"
    report_bytes = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    report_path.write_bytes(report_bytes)
    stage["status"] = "complete" if passed else "in_progress"
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
