"""Simulated fault-case evaluation (P3): workflow + field evidence."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from react_agent.apps.docs_troubleshoot.eval_golden import score_workflow_case
from react_agent.apps.docs_troubleshoot.eval_production import production_corpus_dir
from react_agent.apps.docs_troubleshoot.index import reset_index

_FAULT = Path(__file__).resolve().parent / "fault_cases.json"


def load_fault_cases() -> list[dict[str, Any]]:
    """加载冻结故障注入集及其期望根因和证据。"""
    return json.loads(_FAULT.read_text(encoding="utf-8"))


def _initial_state(case: dict[str, Any]) -> dict[str, Any]:
    state: dict[str, Any] = {"query": case["question"]}
    for key in (
        "error_response",
        "request_headers",
        "log_excerpt",
        "trace_context",
        "trace_id",
    ):
        if case.get(key) is not None:
            state[key] = case[key]
    return state


def _case_needs_production_corpus(case: dict[str, Any]) -> bool:
    pref = " ".join(case.get("prefer_sources") or [])
    if "prod_" in pref:
        return True
    return case.get("log_excerpt") is not None or case.get("trace_context") is not None


def _configure_ingest_for_case(case: dict[str, Any]) -> None:
    prod = str(production_corpus_dir())
    if _case_needs_production_corpus(case):
        os.environ["REACT_AGENT_DOCS_INGEST_DIRS"] = prod
    else:
        os.environ.pop("REACT_AGENT_DOCS_INGEST_DIRS", None)


def _diagnosis_blob(diagnosis: dict[str, Any]) -> str:
    return json.dumps(diagnosis, ensure_ascii=False).lower()


def score_diagnosis(case: dict[str, Any], diagnosis: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    """Score root-cause hints, evidence sufficiency, and forbidden suggestions."""
    if not row.get("passed"):
        row["root_cause_ok"] = False
        row["wrong_suggestion"] = False
        row["evidence_sufficiency"] = diagnosis.get("evidence_sufficiency")
        row["evidence_sufficiency_applicable"] = bool(
            diagnosis.get("evidence_sufficiency_applicable")
        )
        return row

    expect_rc = case.get("expect_root_cause") or []
    blob = _diagnosis_blob(diagnosis)
    causes = diagnosis.get("candidate_causes") or []
    cause_text = json.dumps(causes, ensure_ascii=False).lower()
    fix_text = json.dumps(diagnosis.get("fix_steps") or [], ensure_ascii=False).lower()
    answer_text = str(diagnosis.get("answer_summary") or "").lower()
    combined = f"{blob} {cause_text} {fix_text} {answer_text}"

    if expect_rc:
        row["root_cause_ok"] = all(k.lower() in combined for k in expect_rc)
    else:
        row["root_cause_ok"] = True

    forbid = case.get("forbid_any") or []
    row["wrong_suggestion"] = any(k.lower() in combined for k in forbid) if forbid else False
    row["evidence_sufficiency"] = diagnosis.get("evidence_sufficiency")
    row["evidence_sufficiency_applicable"] = bool(
        diagnosis.get("evidence_sufficiency_applicable")
    )

    if not row["root_cause_ok"]:
        row["passed"] = False
        row["fail_reason"] = (row.get("fail_reason") or "") + ",root_cause"
    if row["wrong_suggestion"]:
        row["passed"] = False
        row["fail_reason"] = (row.get("fail_reason") or "") + ",wrong_suggestion"

    return row


def compute_fault_metrics(
    cases: list[dict[str, Any]],
    rows: list[dict[str, Any]],
) -> dict[str, float | int | None]:
    """计算根因命中、证据充分和错误建议等诊断指标。"""
    total = len(rows) or 1
    rc_hits = sum(1 for r in rows if r.get("root_cause_ok"))
    sufficiency_scores = [
        float(r["evidence_sufficiency"])
        for r in rows
        if r.get("evidence_sufficiency_applicable")
        and r.get("evidence_sufficiency") is not None
    ]
    wrong = sum(1 for r in rows if r.get("wrong_suggestion"))
    return {
        "root_cause_hit_rate": round(rc_hits / total, 3),
        "evidence_sufficiency_rate": (
            round(sum(sufficiency_scores) / len(sufficiency_scores), 3)
            if sufficiency_scores
            else None
        ),
        "evidence_sufficiency_sample_size": len(sufficiency_scores),
        "wrong_suggestion_rate": round(wrong / total, 3),
    }


def run_fault_eval() -> dict[str, Any]:
    """运行故障集并返回可用于回归门禁的聚合报告。"""
    os.environ.setdefault("REACT_AGENT_APP", "docs_troubleshoot")
    os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")

    from react_agent.tools import enable_app_tools
    from react_agent.workflow import run_workflow

    enable_app_tools()

    cases = load_fault_cases()
    rows: list[dict[str, Any]] = []
    for case in cases:
        _configure_ingest_for_case(case)
        reset_index()
        result = run_workflow("docs_troubleshoot", _initial_state(case))
        row = score_workflow_case(
            case,
            answer=result.answer,
            refused=bool(result.refused),
            ok_run=bool(result.ok),
        )
        row = score_diagnosis(case, result.diagnosis or {}, row)
        row["diagnosis"] = result.diagnosis
        rows.append(row)

    passed = sum(1 for r in rows if r["passed"])
    total = len(rows)
    by_tag: dict[str, dict[str, int]] = {}
    for case, row in zip(cases, rows):
        tag = str(case.get("tag") or "fault_sim")
        bucket = by_tag.setdefault(tag, {"passed": 0, "total": 0})
        bucket["total"] += 1
        if row["passed"]:
            bucket["passed"] += 1

    metrics = compute_fault_metrics(cases, rows)

    return {
        "suite": "fault_sim",
        "passed": passed,
        "total": total,
        "pass_rate": round(passed / total, 3) if total else 0.0,
        "metrics": metrics,
        "by_tag": by_tag,
        "rows": rows,
    }


if __name__ == "__main__":
    report = run_fault_eval()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["passed"] == report["total"] else 1)
