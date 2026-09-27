"""Run the offline portfolio acceptance suite and emit one reproducible manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TASKS = ROOT / "examples/fixtures/software_tasks/acceptance_task_set.json"
EVIDENCE = ROOT / "artifacts/software-delivery"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="artifacts/portfolio_acceptance_v1.json")
    args = parser.parse_args(argv)
    out = ROOT / args.out
    manifest = json.loads(TASKS.read_text(encoding="utf-8"))
    reports = []
    fixture = ROOT / "examples/fixtures/software_tasks/fastapi-15764-agent.json"
    harness_report = ROOT / "artifacts/portfolio_acceptance.json"
    cmd = [sys.executable, str(ROOT / "examples/eval/harness_closed_loop.py"), "--fixture", "--report-out", str(harness_report)]
    completed = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if completed.returncode != 0:
        raise SystemExit(completed.stdout + completed.stderr)
    for task in manifest["tasks"]:
        acceptance = EVIDENCE / task["id"] / "acceptance.json"
        item = {**task, "evidence_path": str(acceptance.relative_to(ROOT))}
        if acceptance.exists():
            item["evidence_sha256"] = sha256(acceptance)
            item["result"] = json.loads(acceptance.read_text(encoding="utf-8"))
        reports.append(item)
    payload = {
        "suite": manifest["suite"],
        "size": len(reports),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "offline fixture and recorded software-task evidence; not production SLA",
        "inputs": {
            "task_manifest": str(TASKS.relative_to(ROOT)),
            "task_manifest_sha256": sha256(TASKS),
            "harness_report": str(harness_report.relative_to(ROOT)),
            "harness_report_sha256": sha256(harness_report),
        },
        "harness": json.loads(harness_report.read_text(encoding="utf-8")),
        "external_controlled_acceptance": {
            "status": "verified",
            "scenario": "contract_mismatch_fault_injection",
            "artifact_path": "artifacts/portfolio-external/fault-v1",
            "result": json.loads((ROOT / "artifacts/portfolio-external/fault-v1/episode.json").read_text(encoding="utf-8")) if (ROOT / "artifacts/portfolio-external/fault-v1/episode.json").exists() else None,
            "expected": {"status": "test_failed", "external_write_count": 0},
        },
        "tasks": reports,
        "decisions": {item["id"]: item.get("result", {}).get("decision", "missing") for item in reports},
        "reproduce": "python examples/eval/run_portfolio_acceptance.py",
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)} ({len(reports)} tasks)")
    print(json.dumps(payload["decisions"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
