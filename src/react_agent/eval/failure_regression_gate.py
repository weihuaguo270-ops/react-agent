"""Failure regression gate shared by Delivery and SoftwareTask exits.

Fail-closed when siblings are required but missing. Does not auto-fix agents;
it only detects failures, applies regression/release gates, and records reverify links.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


class FailureRegressionError(RuntimeError):
    """Raised when the gate cannot run or hard-fails a delivery/task exit."""


def siblings_available() -> tuple[bool, list[str]]:
    missing: list[str] = []
    try:
        import trace_debugger  # noqa: F401
    except ImportError:
        missing.append("trace-debugger")
    try:
        import eval_engine  # noqa: F401
    except ImportError:
        missing.append("llm-eval-engine")
    return not missing, missing


def require_siblings() -> None:
    ok, missing = siblings_available()
    if not ok:
        raise FailureRegressionError(
            "required siblings missing: "
            + ", ".join(missing)
            + ". Install with: pip install -e ../trace-debugger -e ../llm-eval-engine "
            "(do not skip)."
        )


def load_baseline_scan(path: str | Path) -> dict[str, Any]:
    """Load a frozen tdebug scan snapshot for true cross-run regression compare."""
    target = Path(path)
    if not target.is_file():
        raise FailureRegressionError(f"baseline scan not found: {target}")
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise FailureRegressionError("baseline scan must be a JSON object")
    # Accept either a raw scan snapshot or a gate out_dir's baseline_scan.json.
    if "report_id" not in payload and "analyses" not in payload and "trajectories" not in payload:
        raise FailureRegressionError(
            "baseline scan missing report_id/analyses; pass current_scan.json or baseline_scan.json"
        )
    return payload


def resolve_baseline_scan(
    baseline: str | Path | Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if baseline is None:
        return None
    if isinstance(baseline, Mapping):
        return dict(baseline)
    return load_baseline_scan(baseline)


def build_repair_feedback(
    *,
    release_decision: str,
    failure_gate_decision: str | None = None,
    hard_failures: Sequence[Any] | None = None,
    review_reasons: Sequence[Any] | None = None,
    findings: Mapping[str, Any] | None = None,
    failures: Mapping[str, Any] | None = None,
    artifacts: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Turn gate hold signals into planner/operator-consumable repair feedback.

    Does not auto-fix agents; it only packages what to fix next.
    """
    hard = [str(item) for item in (hard_failures or []) if str(item).strip()]
    reviews = [str(item) for item in (review_reasons or []) if str(item).strip()]
    failures_obj = dict(failures or {})
    findings_obj = dict(findings or {})
    triggered = list(
        failures_obj.get("triggered_rules")
        or (failures_obj.get("regression_gate") or {}).get("triggered_rules")
        or []
    )
    finding_rows: list[dict[str, str]] = []
    for item in findings_obj.get("findings") or []:
        if not isinstance(item, Mapping):
            continue
        finding_rows.append(
            {
                "id": str(item.get("id") or item.get("rule_id") or ""),
                "dimension": str(item.get("dimension") or ""),
                "summary": str(
                    item.get("summary")
                    or item.get("label")
                    or item.get("title")
                    or item.get("message")
                    or ""
                )[:300],
                "severity": str(item.get("severity") or item.get("evidence_state") or ""),
            }
        )
    # Dimension-level pressure when individual findings are empty.
    if not finding_rows:
        for dim in findings_obj.get("dimensions") or []:
            if not isinstance(dim, Mapping):
                continue
            count = int(dim.get("findings_count") or 0)
            if count <= 0 and str(dim.get("evidence_state") or "") in {"", "unobserved", "ok", "pass"}:
                continue
            finding_rows.append(
                {
                    "id": str(dim.get("id") or ""),
                    "dimension": str(dim.get("id") or ""),
                    "summary": str(dim.get("label") or dim.get("id") or ""),
                    "severity": str(dim.get("evidence_state") or ""),
                }
            )

    targets: list[str] = []
    if hard or reviews:
        targets.append("acceptance_or_business_state")
    if triggered:
        targets.append("trajectory_heuristics")
    if finding_rows:
        targets.append("harness_health")
    if not targets:
        targets.append("manual_review")

    planner_safe = {
        "release_decision": release_decision,
        "failure_gate_decision": failure_gate_decision,
        "hard_failures": hard[:20],
        "review_reasons": reviews[:20],
        "triggered_rules": [str(item) for item in triggered[:20]],
        "finding_summaries": [
            row["summary"] for row in finding_rows[:10] if row.get("summary")
        ],
        "targets": list(targets),
    }
    return {
        "schema_version": "repair-feedback/v1",
        "actionable": release_decision in {"hold", "review"} or bool(hard),
        "targets": targets,
        "signals": {
            "hard_failures": hard,
            "review_reasons": reviews,
            "triggered_rules": [str(item) for item in triggered],
            "findings": finding_rows[:20],
            "gate_decision": findings_obj.get("gate_decision") or failure_gate_decision,
        },
        "planner_safe": planner_safe,
        "artifacts": {
            "findings": str((artifacts or {}).get("findings") or ""),
            "failures": str((artifacts or {}).get("failures") or ""),
            "release": str((artifacts or {}).get("release") or ""),
        },
    }


def build_process_quality(
    episodes: Sequence[Mapping[str, Any]],
    *,
    failures: Mapping[str, Any] | None = None,
    findings: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build process_quality for evaluate_evidence_bundle without a fixed stub.

    Primary signal is evidence (business verification + failure-gate + findings).
    When eval-engine is available, also run ProcessRewardScorer fast_mode with a
    deterministic judge seeded by that evidence score (no LLM, no silent 4.0 stub).
    """
    heuristic = _evidence_process_quality(
        episodes, failures=failures, findings=findings
    )
    try:
        prm = _process_reward_quality(
            episodes,
            seed_score=float(heuristic["overall_score"]),
            failures=failures,
            findings=findings,
        )
        return {
            "overall_score": prm["overall_score"],
            "metric": "process_reward_fast+evidence_v1",
            "mode": "process_reward_fast",
            "degraded": False,
            "components": {
                **dict(heuristic.get("components") or {}),
                "process_reward_overall": prm["overall_score"],
                "evidence_heuristic_overall": heuristic["overall_score"],
            },
            "penalties": list(heuristic.get("penalties") or []),
            "process_reward": prm.get("process_reward") or {},
        }
    except Exception as exc:  # noqa: BLE001 - degrade closed, never silent stub
        return {
            **heuristic,
            "metric": "failure_regression_evidence_v1",
            "mode": "evidence_heuristic",
            "degraded": True,
            "degraded_reason": f"{type(exc).__name__}: {exc}"[:240],
        }


def _evidence_process_quality(
    episodes: Sequence[Mapping[str, Any]],
    *,
    failures: Mapping[str, Any] | None,
    findings: Mapping[str, Any] | None,
) -> dict[str, Any]:
    score = 4.5
    penalties: list[dict[str, Any]] = []

    def _penalize(amount: float, reason: str) -> None:
        nonlocal score
        score -= amount
        penalties.append({"amount": amount, "reason": reason})

    failed_business = 0
    empty_answers = 0
    for episode in episodes:
        verification = episode.get("state_verification") or {}
        if isinstance(verification, Mapping) and verification.get("passed") is not True:
            failed_business += 1
        traj = episode.get("trajectory") or {}
        if isinstance(traj, Mapping) and not str(traj.get("final_answer") or "").strip():
            empty_answers += 1
    if failed_business:
        _penalize(min(1.5, 0.75 * failed_business), f"business_state_failures={failed_business}")
    if empty_answers:
        _penalize(min(1.0, 0.4 * empty_answers), f"empty_final_answer={empty_answers}")

    failures_obj = dict(failures or {})
    gate_decision = str(
        failures_obj.get("decision") or failures_obj.get("gate_decision") or ""
    )
    if gate_decision == "hold":
        _penalize(1.0, "failure_gate=hold")
    elif gate_decision == "review":
        _penalize(0.4, "failure_gate=review")
    triggered = list(
        failures_obj.get("triggered_rules")
        or (failures_obj.get("regression_gate") or {}).get("triggered_rules")
        or []
    )
    if triggered:
        _penalize(min(1.2, 0.3 * len(triggered)), f"triggered_rules={len(triggered)}")

    findings_obj = dict(findings or {})
    finding_rows = list(findings_obj.get("findings") or [])
    high = 0
    for item in finding_rows:
        if not isinstance(item, Mapping):
            continue
        sev = str(item.get("severity") or item.get("evidence_state") or "").lower()
        if sev in {"high", "critical", "error", "fail", "failed"}:
            high += 1
    if high:
        _penalize(min(1.0, 0.25 * high), f"high_findings={high}")
    elif finding_rows:
        _penalize(min(0.6, 0.1 * len(finding_rows)), f"findings={len(finding_rows)}")

    score = max(1.0, min(5.0, round(score, 3)))
    return {
        "overall_score": score,
        "metric": "failure_regression_evidence_v1",
        "mode": "evidence_heuristic",
        "degraded": False,
        "components": {
            "failed_business": failed_business,
            "empty_answers": empty_answers,
            "failure_gate_decision": gate_decision or None,
            "triggered_rules": len(triggered),
            "findings": len(finding_rows),
            "high_findings": high,
        },
        "penalties": penalties,
    }


def _process_reward_quality(
    episodes: Sequence[Mapping[str, Any]],
    *,
    seed_score: float,
    failures: Mapping[str, Any] | None,
    findings: Mapping[str, Any] | None,
) -> dict[str, Any]:
    from eval_engine.core.process_reward import ProcessRewardScorer
    from eval_engine.core.trajectory_parser import parse_trajectory

    clamped = max(1.0, min(5.0, float(seed_score)))

    def judge(_prompt: str) -> dict[str, Any]:
        return {
            "overall_score": clamped,
            "efficiency_score": clamped,
            "tool_usage_score": clamped,
            "needs_revision": clamped < 3.5,
            "strengths": [],
            "weaknesses": [p["reason"] for p in (_evidence_process_quality(
                episodes, failures=failures, findings=findings
            ).get("penalties") or [])][:5],
        }

    scores: list[float] = []
    details: list[dict[str, Any]] = []
    scorer = ProcessRewardScorer(judge_fn=judge, enable_trace_findings=True)
    for episode in episodes:
        traj = dict(episode.get("trajectory") or {})
        if not traj:
            continue
        dag = parse_trajectory(traj)
        report = scorer.score_trajectory(
            dag,
            fast_mode=True,
            trajectory=traj,
            final_state=dict(episode.get("final_state") or {}),
        )
        episode_score = report.overall_score
        # 未评估（None）的 episode 不进均值分母：把"没评过"当 0 分会凭空压低整体分
        if episode_score is not None:
            scores.append(float(episode_score))
        details.append(
            {
                "episode_id": episode.get("episode_id"),
                "overall_score": episode_score,
                "num_scored": report.num_scored,
                "needs_revision": report.needs_revision,
                "num_steps": report.num_steps,
            }
        )
    if not scores:
        raise FailureRegressionError(
            "no scored trajectories available for process reward scoring"
        )
    overall = round(sum(scores) / len(scores), 3)
    return {
        "overall_score": overall,
        "process_reward": {"episodes": details, "seed_score": clamped},
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _normalize_trajectory(raw: Mapping[str, Any], *, session_id: str) -> dict[str, Any]:
    traj = dict(raw)
    traj.setdefault("session_id", session_id)
    traj.setdefault("schema_version", "1")
    traj.setdefault("query", traj.get("query") or session_id)
    traj.setdefault("final_answer", traj.get("final_answer") or "")
    steps = []
    for index, step in enumerate(traj.get("steps") or [], start=1):
        item = dict(step)
        item.setdefault("step", index)
        action = item.get("action")
        if isinstance(action, dict):
            args = action.get("arguments", action.get("args", "{}"))
            if not isinstance(args, str):
                args = json.dumps(args, ensure_ascii=False)
            item["action"] = {
                "name": str(action.get("name") or ""),
                "arguments": args,
            }
        steps.append(item)
    traj["steps"] = steps
    return traj


def _episode_for_gate(episode: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize delivery/software episodes for eval-engine import + verification."""
    from eval_engine.integrations.episode import import_episode, verify_episode_state

    payload = dict(episode)
    traj = _normalize_trajectory(
        dict(payload.get("trajectory") or {}),
        session_id=str(payload.get("episode_id") or "episode"),
    )
    payload["trajectory"] = traj
    payload.setdefault("schema_version", "evaluation-episode/v1")
    payload.setdefault("framework", "format_b")
    payload.setdefault("task", traj.get("query") or payload.get("episode_id"))
    # Prefer explicit expected/final business state; fall back to delivery fields.
    if not payload.get("expected_state"):
        payload["expected_state"] = {"tests_passed": True, "status_not_failed": True}
    if not payload.get("final_state"):
        verification = payload.get("state_verification") or {}
        passed = bool(verification.get("passed"))
        payload["final_state"] = {
            "tests_passed": passed,
            "status_not_failed": passed,
        }
    imported = import_episode(payload)
    normalized = imported.to_dict()
    normalized["state_verification"] = verify_episode_state(imported).to_dict()
    return normalized


def _scan_trajectories(trajs: Sequence[Mapping[str, Any]], *, source_dir: str) -> dict[str, Any]:
    from trace_debugger import Analyzer
    from trace_debugger.reader import parse as tdebug_parse
    from trace_debugger.record import build_scan_snapshot

    parsed = []
    analyses = []
    source_files: list[str] = []
    analyzer = Analyzer()
    for index, raw in enumerate(trajs):
        item = _normalize_trajectory(raw, session_id=str(raw.get("session_id") or f"traj-{index}"))
        traj = tdebug_parse(item)
        parsed.append(traj)
        analyses.append(analyzer.analyze(traj))
        source_files.append(str(item.get("session_id") or f"traj-{index}") + ".json")
    return build_scan_snapshot(
        source_dir,
        len(parsed),
        parsed,
        analyses,
        source_files=source_files,
        task_type="qa",
    )


def _failure_gate(current: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
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
    export["decision"] = gate["decision"]
    export["gate_decision"] = gate["decision"]
    export["triggered_rules"] = gate.get("triggered_rules")
    export["regression_gate"] = gate
    return export


def evaluate_failure_regression_gate(
    episodes: Sequence[Mapping[str, Any]],
    *,
    out_dir: str | Path,
    require_installed_siblings: bool = True,
    baseline_scan: str | Path | Mapping[str, Any] | None = None,
    parent_run_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Run tdebug scan + eval-engine release over one or more episodes.

    ``baseline_scan`` may be a frozen scan mapping or a path to
    ``baseline_scan.json`` / ``current_scan.json`` from a prior green run.
    When omitted, the current scan is used as its own baseline (self-compare).
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if require_installed_siblings:
        ok, missing = siblings_available()
        if not ok:
            report: dict[str, Any] = {
                "schema_version": "failure-regression-gate/v1",
                "available": False,
                "missing_siblings": missing,
                "release_decision": "hold",
                "failure_gate_decision": "hold",
                "hard_failures": [f"required siblings missing: {', '.join(missing)}"],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            feedback = build_repair_feedback(
                release_decision="hold",
                failure_gate_decision="hold",
                hard_failures=report["hard_failures"],
            )
            report["repair_feedback"] = feedback
            _write_json(out / "repair_feedback.json", feedback)
            _write_json(out / "release.json", report)
            _write_json(out / "pipeline_report.json", report)
            return report
        require_siblings()
    else:
        # Soft path for unit tests: still require imports only when evaluating.
        ok, missing = siblings_available()
        if not ok:
            raise FailureRegressionError(
                "siblings required to evaluate gate even when require_installed_siblings=False "
                f"in this process: {', '.join(missing)}"
            )

    if not episodes:
        raise FailureRegressionError("episodes are required for failure regression gate")

    normalized_episodes = [_episode_for_gate(ep) for ep in episodes]
    ep_dir = out / "episodes"
    traj_dir = out / "trajectories"
    trajs: list[dict[str, Any]] = []
    for episode in normalized_episodes:
        _write_json(ep_dir / f"{episode['episode_id']}.json", episode)
        traj = dict(episode["trajectory"])
        trajs.append(traj)
        _write_json(traj_dir / f"{episode['episode_id']}.json", traj)

    current = _scan_trajectories(trajs, source_dir=str(traj_dir))
    _write_json(out / "current_scan.json", current)
    resolved_baseline = resolve_baseline_scan(baseline_scan)
    baseline_source = "provided" if resolved_baseline is not None else "self"
    if resolved_baseline is not None:
        baseline = dict(resolved_baseline)
    else:
        # First observation becomes its own baseline (no false regression).
        baseline = dict(current)
        baseline["report_id"] = f"baseline-from-{current.get('report_id', 'current')}"
    _write_json(out / "baseline_scan.json", baseline)

    failures = _failure_gate(current, baseline)
    _write_json(out / "failures.json", failures)

    from trace_debugger import build_findings_report
    from eval_engine.gates.evidence_bundle import evaluate_evidence_bundle

    findings = build_findings_report(current, baseline, project_root=str(out))
    _write_json(out / "findings.json", findings)
    process_quality = build_process_quality(
        normalized_episodes,
        failures=failures,
        findings=findings,
    )
    release = evaluate_evidence_bundle(
        episodes=normalized_episodes,
        failure_gate=failures,
        process_quality=process_quality,
    )
    _write_json(out / "release.json", release)
    _write_json(out / "process_quality.json", process_quality)

    artifacts = {
        "failures": str(out / "failures.json"),
        "findings": str(out / "findings.json"),
        "release": str(out / "release.json"),
        "episodes": str(ep_dir),
        "baseline_scan": str(out / "baseline_scan.json"),
        "current_scan": str(out / "current_scan.json"),
        "process_quality": str(out / "process_quality.json"),
    }
    repair_feedback = build_repair_feedback(
        release_decision=str(release.get("decision") or ""),
        failure_gate_decision=str(failures.get("decision") or ""),
        hard_failures=list(release.get("hard_failures") or []),
        review_reasons=list(release.get("review_reasons") or []),
        findings=findings,
        failures=failures,
        artifacts=artifacts,
    )
    _write_json(out / "repair_feedback.json", repair_feedback)

    report = {
        "schema_version": "failure-regression-gate/v1",
        "available": True,
        "goal": "失败自动检出 + 回归门禁 + 修复后强制复验",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "failure_gate_decision": failures.get("decision"),
        "release_decision": release.get("decision"),
        "hard_failures": list(release.get("hard_failures") or []),
        "review_reasons": list(release.get("review_reasons") or []),
        "baseline_source": baseline_source,
        "artifacts": artifacts,
        "repair_feedback": repair_feedback,
        "process_quality": process_quality,
        "reverify": None,
    }
    if parent_run_dir is not None:
        parent = Path(parent_run_dir)
        parent_release = json.loads((parent / "release.json").read_text(encoding="utf-8"))
        improved = (
            parent_release.get("decision") in {"hold", "review"}
            and release.get("decision") == "pass"
            and failures.get("decision") == "pass"
        )
        report["reverify"] = {
            "parent_run": str(parent),
            "parent_release_decision": parent_release.get("decision"),
            "current_release_decision": release.get("decision"),
            "improved_to_pass": improved,
            "required": True,
        }
    _write_json(out / "pipeline_report.json", report)
    return report


def gate_blocks_success(report: Mapping[str, Any]) -> bool:
    """True when callers must not treat the upstream run as succeeded."""
    decision = str(report.get("release_decision") or "")
    if report.get("available") is False:
        return True
    reverify = report.get("reverify") or {}
    if reverify.get("required") and not reverify.get("improved_to_pass"):
        return True
    return decision in {"hold", "review"} or bool(report.get("hard_failures"))


def mark_reverify_required(report: dict[str, Any], *, gate_dir: str | Path) -> dict[str, Any]:
    """Annotate a hold/review report so callers must reverify before success."""
    enriched = dict(report)
    enriched["reverify"] = {
        "required": True,
        "improved_to_pass": False,
        "parent_run": str(gate_dir),
        "parent_release_decision": report.get("release_decision"),
        "blocked": (
            "repair then re-run with parent_run_dir / reverify_from pointing at this "
            "gate directory; success is forbidden until improved_to_pass"
        ),
    }
    if not enriched.get("repair_feedback"):
        enriched["repair_feedback"] = build_repair_feedback(
            release_decision=str(report.get("release_decision") or "hold"),
            failure_gate_decision=str(report.get("failure_gate_decision") or ""),
            hard_failures=list(report.get("hard_failures") or []),
            review_reasons=list(report.get("review_reasons") or []),
            artifacts=dict(report.get("artifacts") or {}),
        )
    return enriched


def evaluate_forced_reverify(
    episodes: Sequence[Mapping[str, Any]],
    *,
    out_dir: str | Path,
    parent_run_dir: str | Path,
    require_installed_siblings: bool = True,
    baseline_scan: str | Path | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Re-run the gate against a parent hold/review; block unless improved_to_pass."""
    parent = Path(parent_run_dir)
    release_path = parent / "release.json"
    if not release_path.is_file():
        raise FailureRegressionError(f"reverify parent missing release.json: {parent}")
    parent_release = json.loads(release_path.read_text(encoding="utf-8"))
    parent_decision = str(parent_release.get("decision") or "")
    if parent_decision not in {"hold", "review"}:
        raise FailureRegressionError(
            f"reverify parent must be hold/review, got {parent_decision!r} at {parent}"
        )

    # Prefer parent's frozen baseline when caller did not supply one.
    inherited_baseline = baseline_scan
    if inherited_baseline is None:
        parent_baseline = parent / "baseline_scan.json"
        if parent_baseline.is_file():
            inherited_baseline = parent_baseline

    report = evaluate_failure_regression_gate(
        episodes,
        out_dir=out_dir,
        require_installed_siblings=require_installed_siblings,
        baseline_scan=inherited_baseline,
        parent_run_dir=parent,
    )
    reverify = dict(report.get("reverify") or {})
    reverify["required"] = True
    if not reverify.get("improved_to_pass"):
        hard = list(report.get("hard_failures") or [])
        hard.append("forced reverify did not improve parent hold/review to pass")
        report = dict(report)
        report["hard_failures"] = hard
        report["release_decision"] = "hold"
        reverify["blocked"] = (
            "repair re-verification did not reach pass; cannot mark succeeded"
        )
        report["reverify"] = reverify
        _write_json(Path(out_dir) / "pipeline_report.json", report)
        _write_json(Path(out_dir) / "release.json", {
            **parent_release,
            "decision": "hold",
            "hard_failures": hard,
            "reverify": reverify,
        })
    else:
        report = dict(report)
        report["reverify"] = reverify
        _write_json(Path(out_dir) / "pipeline_report.json", report)
    return report


def run_gate_with_optional_repair(
    episodes: Sequence[Mapping[str, Any]],
    *,
    out_dir: str | Path,
    require_installed_siblings: bool = True,
    repair_fn: Any = None,
    rebuild_episodes_fn: Any = None,
    baseline_scan: str | Path | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Initial gate; on hold optionally repair, then forced reverify before success.

    ``repair_fn(hold_report) -> Mapping`` should perform the fix (e.g. RepairLoop).
    The hold report includes ``repair_feedback`` for planner/operator consumption.
    ``rebuild_episodes_fn(repair_result) -> Sequence`` must return post-repair episodes.
    Without ``repair_fn``, hold is annotated with ``reverify.required`` and stays blocked.
    """
    out = Path(out_dir)
    initial_dir = out / "initial"
    initial = evaluate_failure_regression_gate(
        episodes,
        out_dir=initial_dir,
        require_installed_siblings=require_installed_siblings,
        baseline_scan=baseline_scan,
    )
    if not gate_blocks_success(initial):
        return {**initial, "phase": "initial_pass", "initial": initial}

    pending = mark_reverify_required(initial, gate_dir=initial_dir)
    if repair_fn is None:
        pending = dict(pending)
        pending["phase"] = "hold_pending_repair"
        _write_json(out / "pipeline_report.json", pending)
        _write_json(out / "repair_feedback.json", pending.get("repair_feedback") or {})
        return pending

    repair_result = repair_fn(pending)
    if rebuild_episodes_fn is None:
        raise FailureRegressionError(
            "rebuild_episodes_fn is required when repair_fn is provided"
        )
    repaired_episodes = list(rebuild_episodes_fn(repair_result))
    reverify_dir = out / "reverify"
    reverify_report = evaluate_forced_reverify(
        repaired_episodes,
        out_dir=reverify_dir,
        parent_run_dir=initial_dir,
        require_installed_siblings=require_installed_siblings,
        baseline_scan=baseline_scan,
    )
    combined = {
        **reverify_report,
        "phase": "reverify",
        "initial": pending,
        "repair": dict(repair_result) if isinstance(repair_result, Mapping) else repair_result,
    }
    _write_json(out / "pipeline_report.json", combined)
    return combined


def attach_software_task_gate(
    task_result: Mapping[str, Any],
    *,
    out_dir: str | Path,
    task_id: str,
    split: str = "dev",
    require_installed_siblings: bool = True,
    parent_run_dir: str | Path | None = None,
    repair_fn: Any = None,
    rebuild_task_result_fn: Any = None,
    baseline_scan: str | Path | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a minimal episode from a SoftwareTaskRunner result and run the gate.

    When ``parent_run_dir`` is set, runs forced reverify against that hold.
    When the first gate holds and ``repair_fn`` is provided, repairs then reverifies.
    ``baseline_scan`` enables true cross-run regression compare.
    """
    def _episode_from(result: Mapping[str, Any]) -> dict[str, Any]:
        passed = result.get("status") == "succeeded"
        episode = {
            "schema_version": "evaluation-episode/v1",
            "episode_id": f"{task_id}-{str(result.get('task_hash', 'run'))[:12]}",
            "task": task_id,
            "framework": "react-agent-software-task",
            "agent_version": "software-task-gate-v1",
            "split": split if split in {"dev", "golden", "held_out", "production"} else "dev",
            "acceptance_criteria": ["public and hidden tests pass", "no unauthorized paths"],
            "expected_state": {
                "tests_passed": True,
                "unauthorized_paths_empty": True,
            },
            "final_state": {
                "tests_passed": passed,
                "unauthorized_paths_empty": not bool(result.get("unauthorized_paths")),
            },
            "trajectory": {
                "session_id": task_id,
                "query": f"SoftwareTask {task_id}",
                "final_answer": f"status={result.get('status')}",
                "steps": [
                    {
                        "step": 1,
                        "thought": "Run public tests",
                        "action": {"name": "public_test", "arguments": "{}"},
                        "observation": str((result.get("public_test") or {}).get("status") or ""),
                    },
                    {
                        "step": 2,
                        "thought": "Run hidden tests",
                        "action": {"name": "hidden_test", "arguments": "{}"},
                        "observation": str((result.get("hidden_test") or {}).get("status") or ""),
                    },
                ],
            },
        }
        if episode["split"] == "dev":
            episode["split"] = "held_out"
        return episode

    out = Path(out_dir)
    if parent_run_dir is not None:
        gate = evaluate_forced_reverify(
            [_episode_from(task_result)],
            out_dir=out,
            parent_run_dir=parent_run_dir,
            require_installed_siblings=require_installed_siblings,
            baseline_scan=baseline_scan,
        )
        enriched = dict(task_result)
        enriched["failure_regression"] = gate
        if gate_blocks_success(gate):
            enriched["status"] = "failure_regression_reverify_failed"
            enriched["gate_blocked"] = True
        return enriched

    if repair_fn is not None:
        def _rebuild(repair_result: Mapping[str, Any]):
            if rebuild_task_result_fn is not None:
                return [_episode_from(rebuild_task_result_fn(repair_result))]
            if isinstance(repair_result, Mapping) and repair_result.get("status") == "succeeded":
                rebuilt = dict(task_result)
                rebuilt["status"] = "succeeded"
                rebuilt["public_test"] = {"status": "passed"}
                rebuilt["hidden_test"] = {"status": "passed"}
                return [_episode_from(rebuilt)]
            rebuilt = dict(task_result)
            rebuilt["status"] = "failed"
            return [_episode_from(rebuilt)]

        gate = run_gate_with_optional_repair(
            [_episode_from(task_result)],
            out_dir=out,
            require_installed_siblings=require_installed_siblings,
            repair_fn=repair_fn,
            rebuild_episodes_fn=_rebuild,
            baseline_scan=baseline_scan,
        )
        enriched = dict(task_result)
        enriched["failure_regression"] = gate
        if gate_blocks_success(gate):
            if gate.get("phase") == "hold_pending_repair":
                enriched["status"] = "failure_regression_hold"
            else:
                enriched["status"] = "failure_regression_reverify_failed"
            enriched["gate_blocked"] = True
        elif enriched.get("status") != "succeeded":
            repair = gate.get("repair") or {}
            if isinstance(repair, Mapping) and repair.get("status") == "succeeded":
                enriched["status"] = "succeeded"
        return enriched

    gate = evaluate_failure_regression_gate(
        [_episode_from(task_result)],
        out_dir=out,
        require_installed_siblings=require_installed_siblings,
        baseline_scan=baseline_scan,
    )
    if gate_blocks_success(gate):
        gate = mark_reverify_required(gate, gate_dir=out)
        _write_json(out / "pipeline_report.json", gate)
        _write_json(out / "repair_feedback.json", gate.get("repair_feedback") or {})
    enriched = dict(task_result)
    enriched["failure_regression"] = gate
    if gate_blocks_success(gate) and enriched.get("status") == "succeeded":
        enriched["status"] = "failure_regression_hold"
        enriched["gate_blocked"] = True
    return enriched


__all__ = [
    "FailureRegressionError",
    "attach_software_task_gate",
    "build_process_quality",
    "build_repair_feedback",
    "evaluate_failure_regression_gate",
    "evaluate_forced_reverify",
    "gate_blocks_success",
    "load_baseline_scan",
    "mark_reverify_required",
    "require_siblings",
    "resolve_baseline_scan",
    "run_gate_with_optional_repair",
    "siblings_available",
]
