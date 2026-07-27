"""Built-in Core workflows (docs troubleshoot first)."""
from __future__ import annotations

from typing import Any

from react_agent.apps.docs_troubleshoot.diagnosis import build_diagnosis
from react_agent.apps.docs_troubleshoot.draft import as_results, build_draft_from_hits
from react_agent.apps.docs_troubleshoot.evidence import collect_evidence_bundle
from react_agent.workflow.engine import Step, StepKind, WorkflowDef
from react_agent.workflow.registry import register_workflow


def _parse_evidence(state: dict[str, Any], **_: Any) -> dict[str, Any]:
    bundle = collect_evidence_bundle(state)
    return {"evidence_bundle": bundle}


def _draft_from_hits(state: dict[str, Any], **_: Any) -> dict[str, Any]:
    out = build_draft_from_hits(
        str(state.get("query") or ""),
        state.get("search_hits"),
        state.get("api_hits"),
        evidence_bundle=state.get("evidence_bundle"),
    )
    return out


def _apply_policy(state: dict[str, Any], **_: Any) -> dict[str, Any]:
    from react_agent.apps.docs_troubleshoot.policy import enforce_answer_policy

    out = enforce_answer_policy(
        str(state.get("draft") or ""),
        allowed_sources=state.get("allowed_sources") or None,
        must_refuse=bool(state.get("need_refuse")),
    )
    return {
        "answer": out["answer"],
        "refused": out.get("refused", False),
        "citations": out.get("citations") or [],
        "policy": out.get("policy"),
    }


def _build_diagnosis(state: dict[str, Any], **_: Any) -> dict[str, Any]:
    hits = as_results(state.get("search_hits")) + as_results(state.get("api_hits"))
    diag = build_diagnosis(
        query=str(state.get("query") or ""),
        evidence_bundle=state.get("evidence_bundle") or {},
        draft=str(state.get("answer") or state.get("draft") or ""),
        ranked_sources=list(state.get("ranked_sources") or []),
        refused=bool(state.get("refused")),
        retrieval_hits=hits,
    )
    diag["answer_summary"] = str(state.get("answer") or diag.get("answer_summary") or "")
    return {"diagnosis": diag}


def _finalize(state: dict[str, Any], **_: Any) -> dict[str, Any]:
    diagnosis = dict(state.get("diagnosis") or {})
    return {
        "answer": state.get("answer") or "",
        "refused": bool(state.get("refused")),
        "citations": list(state.get("citations") or []),
        "diagnosis": diagnosis,
        "done": True,
    }


def build_docs_troubleshoot_workflow() -> WorkflowDef:
    return WorkflowDef(
        name="docs_troubleshoot",
        description="证据化文档排障 v5：日志/Trace + 现场证据 → 检索 → 文档推断诊断",
        version="5",
        handlers={
            "parse_evidence": _parse_evidence,
            "draft_from_hits": _draft_from_hits,
            "apply_policy": _apply_policy,
            "build_diagnosis": _build_diagnosis,
            "finalize": _finalize,
        },
        steps=[
            Step(
                id="parse_evidence",
                kind=StepKind.POLICY,
                description="解析现场证据（error/headers/log/trace/config/health）",
                handler="parse_evidence",
            ),
            Step(
                id="search",
                kind=StepKind.TOOL,
                description="检索内部文档/runbook",
                tool="search_docs",
                args={"query": "$query", "top_k": 3},
                output_key="search_hits",
                depends_on=["parse_evidence"],
            ),
            Step(
                id="lookup_api",
                kind=StepKind.TOOL,
                description="补充 API 参考检索",
                tool="lookup_api",
                args={"topic": "$query", "top_k": 2},
                output_key="api_hits",
                depends_on=["search"],
                critical=False,
            ),
            Step(
                id="draft",
                kind=StepKind.POLICY,
                description="检索排序 + 片段 draft",
                handler="draft_from_hits",
                depends_on=["search", "lookup_api", "parse_evidence"],
            ),
            Step(
                id="policy",
                kind=StepKind.POLICY,
                description="引用校验 / 无依据拒答",
                handler="apply_policy",
                depends_on=["draft"],
            ),
            Step(
                id="build_diagnosis",
                kind=StepKind.POLICY,
                description="结构化诊断（现象/原因/证据/验证/升级）",
                handler="build_diagnosis",
                depends_on=["policy", "parse_evidence"],
            ),
            Step(
                id="final",
                kind=StepKind.FINAL,
                description="定稿输出",
                handler="finalize",
                depends_on=["build_diagnosis"],
            ),
        ],
    )


def register_builtin_workflows() -> None:
    register_workflow(build_docs_troubleshoot_workflow())
