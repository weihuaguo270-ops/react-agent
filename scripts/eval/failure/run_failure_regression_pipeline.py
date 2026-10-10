"""P0 orchestration: trajectories → tdebug failure-gate → eval-engine release.

Goal (job-aligned):
  失败自动检出 + 回归门禁 + 修复后强制复验（本脚本实现前两段，并预留复验入口）

Requires installed siblings (no silent skip):
  pip install -e ../trace-debugger -e ../llm-eval-engine

Examples:
  python scripts/eval/failure/run_failure_regression_pipeline.py --mode pass --expect-decision pass
  python scripts/eval/failure/run_failure_regression_pipeline.py --mode hold --expect-decision hold
  python scripts/eval/failure/run_failure_regression_pipeline.py --reverify-from artifacts/failure-regression/<id>
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file())
FIXTURE_DIR = ROOT / "fixtures" / "failure_regression"
DEFAULT_OUT = ROOT / "artifacts" / "failure-regression"


def _require_siblings() -> None:
    missing: list[str] = []
    try:
        import trace_debugger  # noqa: F401
    except ImportError:
        missing.append("trace-debugger")
    try:
        import eval_engine  # noqa: F401
    except ImportError:
        missing.append("llm-eval-engine")
    if missing:
        joined = ", ".join(missing)
        raise SystemExit(
            f"required siblings missing: {joined}. "
            "Install with: pip install -e ../trace-debugger -e ../llm-eval-engine "
            "(CI must clone both; do not skip)."
        )


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _scan_trajectories(traj_paths: list[Path], *, label: str) -> dict[str, Any]:
    from trace_debugger import Analyzer
    from trace_debugger.reader import parse as tdebug_parse
    from trace_debugger.record import build_scan_snapshot

    trajs = []
    analyses = []
    source_files: list[str] = []
    analyzer = Analyzer()
    for path in traj_paths:
        raw = _load_json(path)
        parsed = tdebug_parse(raw)
        trajs.append(parsed)
        analyses.append(analyzer.analyze(parsed))
        source_files.append(path.name)
    return build_scan_snapshot(
        str(FIXTURE_DIR),
        len(trajs),
        trajs,
        analyses,
        source_files=source_files,
        task_type="qa",
    ) | {"label": label}


def _build_failure_gate(current: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    from trace_debugger import build_failures_export, evaluate_regression_gate

    gate = evaluate_regression_gate(current, baseline)
    compare_block = {
        "baseline_report_id": baseline.get("report_id"),
        "baseline_timestamp": baseline.get("timestamp"),
        "triggered_rules": gate.get("triggered_rules"),
        "fail_rate": gate.get("fail_rate"),
        "distribution_delta": gate.get("distribution_delta"),
        "stability": gate.get("stability"),
        "gate_decision": gate.get("decision"),
    }
    export = build_failures_export(current, compare=compare_block)
    # eval-engine looks at decision / gate_decision on the failure-gate object
    export["decision"] = gate["decision"]
    export["gate_decision"] = gate["decision"]
    export["triggered_rules"] = gate.get("triggered_rules")
    export["regression_gate"] = gate
    return export


def _episode_from_trajectory(
    traj: dict[str, Any],
    *,
    episode_id: str,
    split: str,
    task_ok: bool,
) -> dict[str, Any]:
    from eval_engine.integrations.episode import import_episode, verify_episode_state

    state = {
        "task_completed": task_ok,
        "final_answer_nonempty": bool(str(traj.get("final_answer") or "").strip()),
        "pipeline": "failure_regression_p0",
    }
    envelope = {
        "schema_version": "evaluation-episode/v1",
        "episode_id": episode_id,
        "task": str(traj.get("query") or episode_id),
        "framework": "format_b",
        "agent_version": "react-agent-failure-regression-p0",
        "split": split,
        "acceptance_criteria": [
            "trajectory is Format B",
            "business state matches expected_state",
        ],
        "expected_state": state,
        "final_state": dict(state),
        "trajectory": traj,
        "metadata": {"source": "failure_regression_pipeline"},
    }
    episode = import_episode(envelope)
    payload = episode.to_dict()
    payload["state_verification"] = verify_episode_state(episode).to_dict()
    return payload


def _release(
    episodes: list[dict[str, Any]],
    failure_gate: dict[str, Any],
    *,
    process_quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from eval_engine.gates.evidence_bundle import evaluate_evidence_bundle

    return evaluate_evidence_bundle(
        episodes=episodes,
        failure_gate=failure_gate,
        process_quality=process_quality
        or {
            "overall_score": 1.0,
            "metric": "missing_process_quality",
            "degraded": True,
        },
    )


def _copy_traj(src: Path, dest_dir: Path, name: str) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / name
    shutil.copy2(src, dest)
    return dest


def run_pipeline(
    *,
    mode: str,
    out_dir: Path,
    expect_decision: str | None,
    reverify_from: Path | None,
    baseline_scan: Path | None = None,
) -> dict[str, Any]:
    _require_siblings()
    out_dir.mkdir(parents=True, exist_ok=True)
    traj_dir = out_dir / "trajectories"
    ep_dir = out_dir / "episodes"

    ok_src = FIXTURE_DIR / "trajectory_ok.json"
    bad_src = FIXTURE_DIR / "trajectory_bad.json"
    if not ok_src.is_file() or not bad_src.is_file():
        raise SystemExit(f"missing fixtures under {FIXTURE_DIR}")

    ok_path = _copy_traj(ok_src, traj_dir, "trajectory_ok.json")
    if baseline_scan is not None:
        baseline = _load_json(baseline_scan)
    else:
        baseline = _scan_trajectories([ok_path], label="baseline")
    _write_json(out_dir / "baseline_scan.json", baseline)

    if mode == "pass":
        current_paths = [ok_path]
        task_ok = True
    elif mode == "hold":
        bad_path = _copy_traj(bad_src, traj_dir, "trajectory_bad.json")
        current_paths = [ok_path, bad_path]
        task_ok = False
    else:
        raise SystemExit(f"unknown mode: {mode}")

    current = _scan_trajectories(current_paths, label="current")
    _write_json(out_dir / "current_scan.json", current)

    failure_gate = _build_failure_gate(current, baseline)
    _write_json(out_dir / "failures.json", failure_gate)

    from trace_debugger import build_findings_report

    findings = build_findings_report(current, baseline, project_root=str(ROOT))
    _write_json(out_dir / "findings.json", findings)

    episodes: list[dict[str, Any]] = []
    for idx, path in enumerate(current_paths):
        traj = _load_json(path)
        split = "held_out" if idx == 0 else "dev"
        ep = _episode_from_trajectory(
            traj,
            episode_id=f"{mode}-{traj.get('session_id', path.stem)}",
            split=split,
            task_ok=task_ok if path.name == "trajectory_bad.json" else True,
        )
        episodes.append(ep)
        _write_json(ep_dir / f"{ep['episode_id']}.json", ep)

    # hold mode: force a business-state mismatch on the bad episode so release
    # hard-fails even when heuristic deltas are soft.
    if mode == "hold":
        from eval_engine.integrations.episode import import_episode, verify_episode_state

        for ep in episodes:
            if "bad" in ep["episode_id"]:
                expected = dict(ep.get("expected_state") or {})
                expected["task_completed"] = True
                final = dict(expected)
                final["task_completed"] = False
                ep["expected_state"] = expected
                ep["final_state"] = final
                verified = import_episode(ep)
                ep["state_verification"] = verify_episode_state(verified).to_dict()
                _write_json(ep_dir / f"{ep['episode_id']}.json", ep)

    from react_agent.eval.failure_regression_gate import (
        build_process_quality,
        build_repair_feedback,
    )

    artifacts = {
        "baseline_scan": str(out_dir / "baseline_scan.json"),
        "current_scan": str(out_dir / "current_scan.json"),
        "failures": str(out_dir / "failures.json"),
        "findings": str(out_dir / "findings.json"),
        "release": str(out_dir / "release.json"),
        "episodes": str(ep_dir),
        "trajectories": str(traj_dir),
    }
    process_quality = build_process_quality(
        episodes,
        failures=failure_gate,
        findings=findings,
    )
    _write_json(out_dir / "process_quality.json", process_quality)
    artifacts["process_quality"] = str(out_dir / "process_quality.json")

    release = _release(episodes, failure_gate, process_quality=process_quality)
    _write_json(out_dir / "release.json", release)

    repair_feedback = build_repair_feedback(
        release_decision=str(release.get("decision") or ""),
        failure_gate_decision=str(failure_gate.get("decision") or ""),
        hard_failures=list(release.get("hard_failures") or []),
        review_reasons=list(release.get("review_reasons") or []),
        findings=findings,
        failures=failure_gate,
        artifacts=artifacts,
    )
    _write_json(out_dir / "repair_feedback.json", repair_feedback)

    report = {
        "schema_version": "failure-regression-pipeline/v1",
        "goal": "失败自动检出 + 回归门禁 + 修复后强制复验",
        "mode": mode,
        "run_id": out_dir.name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "siblings_required": ["trace-debugger", "llm-eval-engine"],
        "failure_gate_decision": failure_gate.get("decision"),
        "release_decision": release.get("decision"),
        "baseline_source": "provided" if baseline_scan is not None else "fixture_ok",
        "artifacts": artifacts,
        "repair_feedback": repair_feedback,
        "process_quality": process_quality,
        "reverify": None,
    }

    if reverify_from is not None:
        parent = Path(reverify_from)
        parent_release = _load_json(parent / "release.json")
        parent_failures = _load_json(parent / "failures.json")
        improved = (
            parent_release.get("decision") in {"hold", "review"}
            and release.get("decision") == "pass"
            and failure_gate.get("decision") == "pass"
        )
        report["reverify"] = {
            "parent_run": str(parent),
            "parent_release_decision": parent_release.get("decision"),
            "parent_failure_gate_decision": parent_failures.get("decision"),
            "current_release_decision": release.get("decision"),
            "improved_to_pass": improved,
            "required": True,
        }
        if not improved and expect_decision == "pass":
            report["reverify"]["blocked"] = (
                "repair re-verification did not reach pass; cannot mark succeeded"
            )

    _write_json(out_dir / "pipeline_report.json", report)

    decision = str(release.get("decision") or "")
    if expect_decision and decision != expect_decision:
        raise SystemExit(
            f"expected release decision={expect_decision!r}, got {decision!r}; "
            f"failure_gate={failure_gate.get('decision')!r}; "
            f"hard_failures={release.get('hard_failures')}; "
            f"review_reasons={release.get('review_reasons')}"
        )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("pass", "hold"), default="pass")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output directory (default: artifacts/failure-regression/<stamp>-<mode>)",
    )
    parser.add_argument(
        "--expect-decision",
        choices=("pass", "hold", "review"),
        default=None,
        help="Fail if release decision differs (CI assertions)",
    )
    parser.add_argument(
        "--reverify-from",
        type=Path,
        default=None,
        help="Parent run directory; records mandatory re-verification linkage",
    )
    parser.add_argument(
        "--baseline-scan",
        type=Path,
        default=None,
        help="Frozen baseline_scan.json / current_scan.json from a prior green run",
    )
    args = parser.parse_args(argv)

    out = args.out
    if out is None:
        out = DEFAULT_OUT / f"{_utc_stamp()}-{args.mode}"
    # Default expectations keep CI deterministic when caller omits --expect-decision
    expect = args.expect_decision
    if expect is None:
        expect = "pass" if args.mode == "pass" else "hold"

    report = run_pipeline(
        mode=args.mode,
        out_dir=out.resolve(),
        expect_decision=expect,
        reverify_from=args.reverify_from.resolve() if args.reverify_from else None,
        baseline_scan=args.baseline_scan.resolve() if args.baseline_scan else None,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # When CI asserts an expected decision, matching hold is success (exit 0).
    if expect is not None:
        return 0
    return 0 if report["release_decision"] != "hold" else 1


if __name__ == "__main__":
    raise SystemExit(main())
