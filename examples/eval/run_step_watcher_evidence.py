"""StepWatcher cross-repo E2E evidence — Harness + trace-debugger golden alignment."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TDEBUG = ROOT / "trace-debugger"
if not TDEBUG.is_dir():
    TDEBUG = ROOT.parent / "trace-debugger"
SCENARIOS = ROOT / "fixtures" / "step_watcher_scenarios.json"


def _git_sha() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=ROOT,
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
    except Exception:
        return "unknown"


def run_scenario(scenario: dict, *, traj_dir: Path, log_path: Path) -> dict:
    import os

    os.environ["REACT_AGENT_STEP_WATCHER"] = "1"
    os.environ["REACT_AGENT_FAILURE_LOG"] = str(log_path)

    from react_agent.harness.recorder import TRAJECTORY_DIR, Trajectory
    import react_agent.harness.recorder as rec

    rec.TRAJECTORY_DIR = str(traj_dir)
    traj = Trajectory(scenario["query"], model=scenario.get("model", "mock-gpt"))

    for step in scenario.get("steps") or []:
        if step.get("action_name"):
            traj.add_tool_call(
                step["step"],
                step["action_name"],
                step.get("action_args", ""),
                step.get("observation", ""),
                duration=step.get("duration", 0),
            )
        elif step.get("thought"):
            traj.add_thought(step["step"], step["thought"])
        else:
            traj.add_step(
                step["step"],
                observation=step.get("observation", ""),
            )

    traj.set_final_answer(scenario.get("final_answer", ""))
    filepath = traj.save()

    saved = json.loads(Path(filepath).read_text(encoding="utf-8"))
    jsonl_events = []
    if log_path.is_file():
        jsonl_events = [
            json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()
        ]

    detected_tags = sorted({
        tag
        for s in saved.get("steps") or []
        for tag in (s.get("failure_tags") or [])
    })
    jsonl_types = sorted({e.get("failure_type") for e in jsonl_events if e.get("failure_type")})

    expected = sorted(scenario.get("expected_failures") or [])
    pass_failures = detected_tags == expected

    return {
        "id": scenario["id"],
        "query": scenario.get("query", "")[:80],
        "expected_failures": expected,
        "detected_tags": detected_tags,
        "jsonl_event_types": jsonl_types,
        "jsonl_count": len(jsonl_events),
        "trajectory_path": filepath,
        "pass": pass_failures,
    }


def run_all_scenarios() -> dict:
    data = json.loads(SCENARIOS.read_text(encoding="utf-8"))
    scenarios = data.get("scenarios") or []
    rows = []
    passed = 0
    for i, sc in enumerate(scenarios):
        traj_dir = ROOT / ".evidence_tmp" / f"traj_{i}"
        log_path = ROOT / ".evidence_tmp" / f"log_{i}.jsonl"
        traj_dir.mkdir(parents=True, exist_ok=True)
        if log_path.exists():
            log_path.unlink()
        row = run_scenario(sc, traj_dir=traj_dir, log_path=log_path)
        rows.append(row)
        if row["pass"]:
            passed += 1

    golden_pass_rate = None
    golden_note = "trace-debugger sibling not found"
    if TDEBUG.is_dir():
        cmd = [
            sys.executable, "-m", "pytest",
            str(TDEBUG / "tests" / "test_failure_golden.py"),
            "-q", "--tb=no",
        ]
        proc = subprocess.run(cmd, cwd=str(TDEBUG), capture_output=True, text=True)
        golden_pass_rate = 1.0 if proc.returncode == 0 else 0.0
        golden_note = proc.stdout.strip()[-80:] if proc.stdout else proc.stderr[-80:]

    total = len(rows)
    return {
        "report_id": f"step_watcher_evidence_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "n_scenarios": total,
        "n_passed": passed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "scenarios": rows,
        "golden_suite_pass_rate": golden_pass_rate,
        "golden_suite_note": golden_note,
        "meta": {"git": _git_sha(), "react_agent": str(ROOT), "trace_debugger": str(TDEBUG)},
    }


def to_markdown(report: dict) -> str:
    lines = [
        "# StepWatcher 跨仓证据报告",
        "",
        f"- **report_id:** `{report.get('report_id')}`",
        f"- **timestamp:** `{report.get('timestamp')}`",
        f"- **scenarios:** {report.get('n_scenarios')} (pass {report.get('n_passed')})",
        f"- **pass_rate:** {report.get('pass_rate', 0):.0%}",
        f"- **golden suite (trace-debugger):** {report.get('golden_suite_pass_rate')}",
        f"- **git:** `{((report.get('meta') or {}).get('git'))}`",
        "",
        "## 场景结果",
        "",
        "| id | expected | detected | jsonl | pass |",
        "|----|----------|----------|------:|------|",
    ]
    for row in report.get("scenarios") or []:
        exp = ",".join(row.get("expected_failures") or []) or "-"
        det = ",".join(row.get("detected_tags") or []) or "-"
        icon = "PASS" if row.get("pass") else "FAIL"
        lines.append(
            f"| `{row.get('id')}` | {exp} | {det} | {row.get('jsonl_count', 0)} | {icon} |"
        )

    lines.extend([
        "",
        "## 复现",
        "",
        "```bash",
        "pip install -e ../trace-debugger",
        "python examples/eval/run_step_watcher_evidence.py --publish",
        "python -m pytest tests/test_step_watcher_golden_e2e.py -v",
        "```",
        "",
        "## 诚实边界",
        "",
        "- 场景为 Harness 录制模拟，非 live LLM",
        "- failure_tags 为启发式；与 golden 集分栏引用",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--stem", default="step_watcher_evidence_baseline")
    args = parser.parse_args()

    report = run_all_scenarios()
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if report["n_passed"] != report["n_scenarios"]:
        return 1

    if args.publish:
        docs = ROOT / "docs"
        snap = docs / "snapshots"
        docs.mkdir(exist_ok=True)
        snap.mkdir(exist_ok=True)
        (docs / f"{args.stem}.md").write_text(to_markdown(report), encoding="utf-8")
        (snap / f"{args.stem}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"Published -> docs/{args.stem}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
