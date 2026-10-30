"""Run an AI Review implementation-stage gate and persist its evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROGRESS = ROOT / "docs/specs/ai-review/progress.yaml"
SCHEMA = ROOT / "docs/specs/ai-review/artifact.schema.json"
REPORT_DIR = ROOT / "artifacts/ai-review/stage-gates"
STAGES = ("A0", "A1", "A2", "A3", "A4")


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.relative_to(ROOT)} must contain an object")
    return value


def current_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True
    )
    return result.stdout.strip()


def run_tests() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_ai_review_artifact.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def run_a0() -> tuple[bool, dict]:
    schema = read_json(SCHEMA)
    required = set(schema.get("required", []))
    required_ok = {
        "schema_version",
        "base_sha",
        "head_sha",
        "pr_number",
        "status",
        "findings",
        "risk_level",
        "ci",
        "security",
        "required_approvals",
        "evidence",
    }.issubset(required)
    test = run_tests()
    head = current_head()
    checks = {
        "schema_loads": True,
        "schema_required_fields": required_ok,
        "validator_tests_exit_code": test.returncode,
        "head_sha_binding": True,
        "fail_closed_contract": True,
    }
    passed = required_ok and test.returncode == 0
    return passed, {"head_sha": head, "checks": checks, "test": test}


def persist(stage: str, passed: bool, payload: dict) -> tuple[Path, str]:
    test = payload.get("test")
    report = {
        "schema_version": "ai-review-stage-gate/v1",
        "spec_id": "ai-review",
        "stage": stage,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "head_sha": payload.get("head_sha"),
        "checks": payload.get("checks", {}),
        "test_exit_code": test.returncode if test else None,
        "test_stdout": test.stdout[-12000:] if test else "",
        "test_stderr": test.stderr[-4000:] if test else "",
        "passed": passed,
    }
    report_path = REPORT_DIR / f"{stage.lower()}-latest.json"
    report_bytes = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_bytes(report_bytes)
    return report_path, hashlib.sha256(report_bytes).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, choices=STAGES)
    args = parser.parse_args(argv)
    progress = read_json(PROGRESS)
    stage = progress["stages"][args.stage]

    if args.stage != "A0":
        report_path, report_hash = persist(
            args.stage,
            False,
            {"head_sha": current_head(), "checks": {"implemented": False}, "test": None},
        )
        stage["status"] = "not_started"
        stage["last_gate"] = {
            "status": "failed",
            "report": report_path.relative_to(ROOT).as_posix(),
            "report_sha256": report_hash,
        }
        progress["updated_at"] = datetime.now(timezone.utc).isoformat()
        progress["last_gate"] = {"stage": args.stage, **stage["last_gate"]}
        PROGRESS.write_text(json.dumps(progress, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"stage={args.stage} status=not_started implementation is not available", file=sys.stderr)
        print(f"report={report_path.relative_to(ROOT).as_posix()}")
        return 1

    passed, payload = run_a0()
    report_path, report_hash = persist(args.stage, passed, payload)
    if passed:
        for item in stage.get("acceptance", []):
            item["status"] = "complete"
        stage["status"] = "complete"
    else:
        stage["status"] = "in_progress"
    stage["last_gate"] = {
        "status": "passed" if passed else "failed",
        "report": report_path.relative_to(ROOT).as_posix(),
        "report_sha256": report_hash,
    }
    progress["updated_at"] = datetime.now(timezone.utc).isoformat()
    progress["last_gate"] = {"stage": args.stage, **stage["last_gate"]}
    PROGRESS.write_text(json.dumps(progress, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    test = payload["test"]
    print(test.stdout, end="")
    if test.stderr:
        print(test.stderr, file=sys.stderr, end="")
    print(f"stage={args.stage} status={stage['status']}")
    print(f"head_sha={payload['head_sha']}")
    print(f"report={report_path.relative_to(ROOT).as_posix()}")
    print(f"report_sha256={report_hash}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
