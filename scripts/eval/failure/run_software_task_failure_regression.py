"""Hang FastAPI SoftwareTask Agent runs on the same failure-regression pipeline.

Acceptance (job-aligned):
  1. 15764 / 15974 / 16253 each get independent gate JSON (release/findings/
     process_quality/repair_feedback) matching the fixture pipeline shape.
  2. Frozen baseline_scan: bad patch → hold; good Agent patch → pass.
  3. E2E reverify: hold → good agent → reverify_from → improved_to_pass.
  4. Fail-closed if siblings missing (do not skip).

Examples:
  python scripts/eval/failure/run_software_task_failure_regression.py
  python scripts/eval/failure/run_software_task_failure_regression.py --expect-all-pass-good
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file())
RUNS = ROOT / "artifacts" / "software-tasks" / "runs"
FIXTURE_RUNS = ROOT / "fixtures" / "software_tasks"
DEFAULT_OUT = ROOT / "artifacts" / "failure-regression" / "software-tasks"

TASKS: tuple[tuple[str, str], ...] = (
    ("fastapi-15764-apiroute-tags", "fastapi-15764-agent.json"),
    ("fastapi-15974-router-cache-race", "fastapi-15974-agent.json"),
    ("fastapi-16253-docs-template-xss", "fastapi-16253-agent.json"),
)


def _resolve_agent_run(filename: str) -> Path:
    """Prefer real Agent run JSON; fall back to committed compact fixtures (CI)."""
    primary = RUNS / filename
    if primary.is_file():
        return primary
    fixture = FIXTURE_RUNS / filename
    if fixture.is_file():
        return fixture
    raise SystemExit(
        f"missing agent run JSON: tried {primary} and {fixture} (do not skip)."
    )


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
        raise SystemExit(
            "required siblings missing: "
            + ", ".join(missing)
            + ". Install with: pip install -e ../trace-debugger -e ../llm-eval-engine "
            "(do not skip)."
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _corrupt_as_bad_patch(good: dict[str, Any]) -> dict[str, Any]:
    """Synthesize a failed SoftwareTask envelope (intentional bad patch)."""
    bad = dict(good)
    bad["status"] = "failed"
    bad["exit_code"] = 1
    bad["patch_kind"] = "intentional_bad"
    bad["public_test"] = {
        "status": "failed",
        "returncode": 1,
        "stdout": "FAILED tests/test_intentional_bad.py::test_breaks",
        "stderr": "AssertionError: intentional bad patch",
    }
    bad["hidden_test"] = {}
    bad["unauthorized_paths"] = list(bad.get("unauthorized_paths") or [])
    return bad


def _gate_one(
    task_result: dict[str, Any],
    *,
    task_id: str,
    out_dir: Path,
    baseline_scan: Path | None,
    parent_run_dir: Path | None = None,
) -> dict[str, Any]:
    from react_agent.eval.failure_regression_gate import attach_software_task_gate

    return attach_software_task_gate(
        task_result,
        out_dir=out_dir,
        task_id=task_id,
        split="held_out",
        require_installed_siblings=True,
        baseline_scan=baseline_scan,
        parent_run_dir=parent_run_dir,
    )


def run_acceptance(*, out_root: Path, expect_all_pass_good: bool) -> dict[str, Any]:
    _require_siblings()
    out_root.mkdir(parents=True, exist_ok=True)

    # Phase 0: freeze baseline from first green agent gate (self-scan then reuse).
    first_id, first_file = TASKS[0]
    first_path = _resolve_agent_run(first_file)
    first_good = _load_json(first_path)
    seed_dir = out_root / "baseline-seed" / first_id
    seed = _gate_one(
        first_good,
        task_id=first_id,
        out_dir=seed_dir,
        baseline_scan=None,
    )
    if seed.get("status") == "failure_regression_hold" or (
        seed.get("failure_regression") or {}
    ).get("release_decision") not in {None, "pass"}:
        # Seed may still pass gate when tests succeeded; require pass for baseline.
        fr = seed.get("failure_regression") or {}
        if fr.get("release_decision") != "pass":
            raise SystemExit(
                f"baseline seed did not pass gate: {fr.get('release_decision')} "
                f"hard={fr.get('hard_failures')}"
            )
    baseline_path = Path(
        (seed.get("failure_regression") or {})
        .get("artifacts", {})
        .get("current_scan")
        or (seed_dir / "current_scan.json")
    )
    if not baseline_path.is_file():
        # attach writes under out_dir directly or under initial/
        candidates = [
            seed_dir / "current_scan.json",
            seed_dir / "initial" / "current_scan.json",
        ]
        baseline_path = next((p for p in candidates if p.is_file()), baseline_path)
    if not baseline_path.is_file():
        raise SystemExit(f"frozen baseline missing under {seed_dir}")
    frozen_baseline = out_root / "frozen_baseline_scan.json"
    frozen_baseline.write_text(baseline_path.read_text(encoding="utf-8"), encoding="utf-8")

    per_task: list[dict[str, Any]] = []
    for task_id, filename in TASKS:
        agent_path = _resolve_agent_run(filename)
        good = _load_json(agent_path)
        if good.get("status") != "succeeded":
            raise SystemExit(f"agent run not succeeded: {agent_path}")

        good_dir = out_root / "good" / task_id
        good_enriched = _gate_one(
            good,
            task_id=task_id,
            out_dir=good_dir,
            baseline_scan=frozen_baseline,
        )
        good_fr = good_enriched.get("failure_regression") or {}
        good_decision = str(good_fr.get("release_decision") or "")

        bad = _corrupt_as_bad_patch(good)
        bad_dir = out_root / "bad" / task_id
        bad_enriched = _gate_one(
            bad,
            task_id=task_id,
            out_dir=bad_dir,
            baseline_scan=frozen_baseline,
        )
        bad_fr = bad_enriched.get("failure_regression") or {}
        bad_decision = str(bad_fr.get("release_decision") or "")

        # Persist enriched agent JSON under out_root (and runs/ when present) for audit.
        stem = filename.replace(".json", "")
        enriched_out = out_root / "gated" / f"{stem}-gated.json"
        if RUNS.is_dir():
            runs_gated = RUNS / f"{stem}-gated.json"
            _write_json(
                runs_gated,
                {
                    **good,
                    "failure_regression": good_fr,
                    "gate_artifacts": good_fr.get("artifacts") or {},
                    "baseline_scan": str(frozen_baseline),
                    "agent_run_source": str(agent_path),
                },
            )
            enriched_out = runs_gated
        else:
            _write_json(
                enriched_out,
                {
                    **good,
                    "failure_regression": good_fr,
                    "gate_artifacts": good_fr.get("artifacts") or {},
                    "baseline_scan": str(frozen_baseline),
                    "agent_run_source": str(agent_path),
                },
            )

        record = {
            "task_id": task_id,
            "agent_run": str(agent_path),
            "gated_agent_run": str(enriched_out),
            "good": {
                "out_dir": str(good_dir),
                "release_decision": good_decision,
                "failure_gate_decision": good_fr.get("failure_gate_decision"),
                "baseline_source": good_fr.get("baseline_source"),
                "process_quality_metric": (good_fr.get("process_quality") or {}).get("metric"),
                "repair_feedback_schema": (good_fr.get("repair_feedback") or {}).get(
                    "schema_version"
                ),
                "artifacts": good_fr.get("artifacts") or {},
            },
            "bad": {
                "out_dir": str(bad_dir),
                "release_decision": bad_decision,
                "failure_gate_decision": bad_fr.get("failure_gate_decision"),
                "baseline_source": bad_fr.get("baseline_source"),
                "repair_feedback_actionable": (bad_fr.get("repair_feedback") or {}).get(
                    "actionable"
                ),
                "artifacts": bad_fr.get("artifacts") or {},
            },
        }
        per_task.append(record)

        if expect_all_pass_good and good_decision != "pass":
            raise SystemExit(
                f"{task_id} good agent expected release=pass, got {good_decision!r}; "
                f"hard={good_fr.get('hard_failures')}"
            )
        if bad_decision != "hold":
            raise SystemExit(
                f"{task_id} bad patch expected release=hold, got {bad_decision!r}"
            )
        for name in ("release.json", "findings.json", "process_quality.json", "repair_feedback.json"):
            if not (good_dir / name).is_file() and not (good_dir / "initial" / name).is_file():
                # files are written at out_dir root by evaluate_failure_regression_gate
                if not (good_dir / name).is_file():
                    raise SystemExit(f"missing {name} under {good_dir}")

    # Phase 3: E2E reverify on last task (16253) — hold then improved_to_pass.
    demo_id, demo_file = TASKS[-1]
    demo_good = _load_json(_resolve_agent_run(demo_file))
    demo_bad = _corrupt_as_bad_patch(demo_good)
    hold_dir = out_root / "reverify" / "parent-hold"
    hold_enriched = _gate_one(
        demo_bad,
        task_id=demo_id,
        out_dir=hold_dir,
        baseline_scan=frozen_baseline,
    )
    hold_fr = hold_enriched.get("failure_regression") or {}
    if hold_fr.get("release_decision") != "hold":
        raise SystemExit(
            f"reverify parent must hold, got {hold_fr.get('release_decision')!r}"
        )

    child_dir = out_root / "reverify" / "child-pass"
    child_enriched = _gate_one(
        demo_good,
        task_id=demo_id,
        out_dir=child_dir,
        baseline_scan=frozen_baseline,
        parent_run_dir=hold_dir,
    )
    child_fr = child_enriched.get("failure_regression") or {}
    reverify = child_fr.get("reverify") or {}
    if not reverify.get("improved_to_pass"):
        raise SystemExit(
            "reverify did not improve_to_pass; "
            f"release={child_fr.get('release_decision')} reverify={reverify}"
        )
    if child_fr.get("release_decision") != "pass":
        raise SystemExit(
            f"reverify child expected pass, got {child_fr.get('release_decision')!r}"
        )

    summary = {
        "schema_version": "software-task-failure-regression/v1",
        "goal": "失败自动检出 + 回归门禁 + 修复后强制复验",
        "claim": "对齐工作流已在夹具 + 3 条 SoftwareTask 上复现",
        "timestamp": _utc_now(),
        "frozen_baseline": str(frozen_baseline),
        "tasks": per_task,
        "reverify_playbook": {
            "task_id": demo_id,
            "parent_hold": str(hold_dir),
            "child_pass": str(child_dir),
            "parent_release_decision": hold_fr.get("release_decision"),
            "child_release_decision": child_fr.get("release_decision"),
            "improved_to_pass": reverify.get("improved_to_pass"),
            "required": reverify.get("required"),
        },
        "boundaries": [
            "Does not claim production SLA",
            "Does not claim autonomous Agent self-optimization",
            "Gate episodes are built from SoftwareTask public/hidden outcomes",
        ],
    }
    _write_json(out_root / "acceptance_summary.json", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help="Output root (default: artifacts/failure-regression/software-tasks)",
    )
    parser.add_argument(
        "--expect-all-pass-good",
        action="store_true",
        default=True,
        help="Require good Agent envelopes to release=pass (default on)",
    )
    parser.add_argument(
        "--allow-good-non-pass",
        action="store_true",
        help="Do not fail if a good Agent gate is not pass",
    )
    args = parser.parse_args(argv)
    expect = False if args.allow_good_non_pass else True
    summary = run_acceptance(out_root=args.out.resolve(), expect_all_pass_good=expect)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
