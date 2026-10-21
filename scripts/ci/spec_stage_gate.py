"""Run a phase gate for a feature-owned Spec progress file."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "docs/spec/registry.yaml"


def load_config(spec: str) -> dict:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    try:
        entry = registry["directions"][spec]
        gate = entry["gate"]
        return {
            "progress": ROOT / entry["progress_source"],
            "report_dir": ROOT / gate["artifact_dir"],
            "tests": gate["tests"],
        }
    except KeyError as exc:
        raise SystemExit(f"missing registry gate configuration for {spec!r}: {exc}") from exc


def resolve_repo_path(relative: str) -> Path:
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(ROOT.resolve()):
        raise ValueError(f"path escapes repository: {relative}")
    return path


def check_evidence(items: list[dict]) -> list[dict]:
    results = []
    for item in items:
        missing = [p for p in item.get("evidence", []) if not resolve_repo_path(p).exists()]
        results.append({"id": item["id"], "status": item["status"], "passed": not missing, "missing": missing})
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--stage", required=True)
    args = parser.parse_args()
    config = load_config(args.spec)
    progress_path = config["progress"]
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    if args.stage not in progress["stages"]:
        raise SystemExit(f"unknown stage {args.stage!r} for spec {args.spec!r}")
    stage = progress["stages"][args.stage]
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *config["tests"][args.stage]]
    env = dict(os.environ)
    env["REACT_AGENT_PERMISSIVE_TEST_DIRS"] = "1"
    test = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True, check=False)
    evidence = check_evidence(stage.get("acceptance", []))
    pending = [item["id"] for item in stage["acceptance"] if item["status"] != "complete"]
    passed = test.returncode == 0 and not pending and all(item["passed"] for item in evidence)
    report = {
        "schema_version": "spec-stage-gate/v1",
        "spec_id": args.spec,
        "stage": args.stage,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "command": command,
        "test_exit_code": test.returncode,
        "test_stdout": test.stdout[-12000:],
        "test_stderr": test.stderr[-4000:],
        "acceptance_evidence": evidence,
        "acceptance_pending": pending,
        "passed": passed,
    }
    report_dir = config["report_dir"]
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{args.stage}-latest.json"
    report_bytes = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    report_path.write_bytes(report_bytes)
    stage["status"] = "complete" if passed else "in_progress"
    stage["last_gate"] = {"status": "passed" if passed else "failed", "report": report_path.relative_to(ROOT).as_posix(), "report_sha256": hashlib.sha256(report_bytes).hexdigest()}
    progress["updated_at"] = datetime.now(timezone.utc).isoformat()
    progress["last_gate"] = {"stage": args.stage, **stage["last_gate"]}
    progress_path.write_text(json.dumps(progress, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(test.stdout, end="")
    if test.stderr:
        print(test.stderr, file=sys.stderr, end="")
    print(f"spec={args.spec} stage={args.stage} status={stage['status']}")
    print(f"report={report_path.relative_to(ROOT).as_posix()}")
    print(f"report_sha256={stage['last_gate']['report_sha256']}")
    if pending:
        print("acceptance_pending=" + ",".join(pending))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
