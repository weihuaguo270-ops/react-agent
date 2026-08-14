"""Production blind-set evaluation: external corpus via INGEST_DIRS."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from react_agent.apps.docs_troubleshoot.eval_golden import score_workflow_case
from react_agent.apps.docs_troubleshoot.index import reset_index

_APP = Path(__file__).resolve().parent
_REPO = _APP.resolve().parents[3]
_PRODUCTION_CORPUS = _REPO / "fixtures" / "docs_troubleshoot" / "production_corpus"
_CASES = _APP / "production_cases.json"
DEFAULT_MIN_EVIDENCE_SUFFICIENCY = 0.5


def production_corpus_dir() -> Path:
    """返回生产盲测专用语料目录。"""
    return _PRODUCTION_CORPUS


def load_production_cases() -> list[dict[str, Any]]:
    """加载与开发集隔离的 production/held-out 用例。"""
    return json.loads(_CASES.read_text(encoding="utf-8"))


def _configure_production_ingest() -> None:
    os.environ["REACT_AGENT_DOCS_INGEST_DIRS"] = str(_PRODUCTION_CORPUS)
    os.environ.setdefault("REACT_AGENT_APP", "docs_troubleshoot")
    os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")


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


def _apply_evidence_sufficiency_gate(
    row: dict[str, Any],
    minimum: float | None,
) -> None:
    """现场证据存在时才应用充分度门禁。"""
    if minimum is None or not row.get("evidence_sufficiency_applicable"):
        return
    score = row.get("evidence_sufficiency")
    if score is not None and float(score) >= minimum:
        return
    row["passed"] = False
    reasons = [item for item in str(row.get("fail_reason") or "").split(",") if item]
    reasons.append("evidence_sufficiency")
    row["fail_reason"] = ",".join(reasons)


def run_production_eval(
    *,
    include_held_out: bool = True,
    min_evidence_sufficiency: float | None = DEFAULT_MIN_EVIDENCE_SUFFICIENCY,
) -> dict[str, Any]:
    """运行生产盲测并将证据充分性作为硬门禁写入报告。"""
    _configure_production_ingest()

    from react_agent.tools import enable_app_tools
    from react_agent.workflow import run_workflow

    enable_app_tools()
    reset_index()

    cases = load_production_cases()
    if not include_held_out:
        cases = [c for c in cases if c.get("tag") != "prod_held_out"]

    rows: list[dict[str, Any]] = []
    for case in cases:
        result = run_workflow("docs_troubleshoot", _initial_state(case))
        row = score_workflow_case(
            case,
            answer=result.answer,
            refused=bool(result.refused),
            ok_run=bool(result.ok),
        )
        row["diagnosis"] = result.diagnosis
        if result.diagnosis:
            row["evidence_sufficiency"] = result.diagnosis.get("evidence_sufficiency")
            row["evidence_sufficiency_applicable"] = bool(
                result.diagnosis.get("evidence_sufficiency_applicable")
            )
            row["evidence_mode"] = result.diagnosis.get("evidence_mode")
            row["field_doc_aligned"] = result.diagnosis.get("field_doc_aligned")
        _apply_evidence_sufficiency_gate(row, min_evidence_sufficiency)
        rows.append(row)

    passed = sum(1 for r in rows if r["passed"])
    total = len(rows)
    by_tag: dict[str, dict[str, int]] = {}
    for case, row in zip(cases, rows):
        tag = str(case.get("tag") or "prod_blind")
        bucket = by_tag.setdefault(tag, {"passed": 0, "total": 0})
        bucket["total"] += 1
        if row["passed"]:
            bucket["passed"] += 1

    prod_hits = sum(
        1
        for r in rows
        if any("prod_" in source for source in (r.get("claimed_sources") or []))
    )
    document_evidence_hits = sum(
        1 for r in rows if r.get("ok_cite") and r.get("ok_src")
    )
    applicable_scores = [
        float(r["evidence_sufficiency"])
        for r in rows
        if r.get("evidence_sufficiency_applicable")
        and r.get("evidence_sufficiency") is not None
    ]

    return {
        "suite": "production_blind",
        "corpus": str(_PRODUCTION_CORPUS),
        "passed": passed,
        "total": total,
        "pass_rate": round(passed / total, 3) if total else 0.0,
        "by_tag": by_tag,
        "metrics": {
            "production_source_hit_rate": round(prod_hits / total, 3) if total else 0.0,
            "document_evidence_rate": (
                round(document_evidence_hits / total, 3) if total else 0.0
            ),
            "avg_evidence_sufficiency": (
                round(sum(applicable_scores) / len(applicable_scores), 3)
                if applicable_scores
                else None
            ),
            "evidence_sufficiency_sample_size": len(applicable_scores),
            "min_evidence_sufficiency": min_evidence_sufficiency,
        },
        "rows": rows,
    }


if __name__ == "__main__":
    report = run_production_eval()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["passed"] == report["total"] else 1)
