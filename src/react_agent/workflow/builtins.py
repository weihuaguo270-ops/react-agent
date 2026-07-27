"""Built-in Core workflows (docs troubleshoot first)."""
from __future__ import annotations

from typing import Any

from react_agent.apps.docs_troubleshoot.draft import build_draft_from_hits
from react_agent.workflow.engine import Step, StepKind, WorkflowDef
from react_agent.workflow.registry import register_workflow


def _draft_from_hits(state: dict[str, Any], **_: Any) -> dict[str, Any]:
    return build_draft_from_hits(
        str(state.get("query") or ""),
        state.get("search_hits"),
        state.get("api_hits"),
    )


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


def _finalize(state: dict[str, Any], **_: Any) -> dict[str, Any]:
    return {
        "answer": state.get("answer") or "",
        "refused": bool(state.get("refused")),
        "citations": list(state.get("citations") or []),
        "done": True,
    }


def build_docs_troubleshoot_workflow() -> WorkflowDef:
    return WorkflowDef(
        name="docs_troubleshoot",
        description="证据化文档排障：检索 → 片段 draft → 引用/拒答（非根因诊断 Agent）",
        version="3",
        handlers={
            "draft_from_hits": _draft_from_hits,
            "apply_policy": _apply_policy,
            "finalize": _finalize,
        },
        steps=[
            Step(
                id="search",
                kind=StepKind.TOOL,
                description="检索内部文档/runbook",
                tool="search_docs",
                args={"query": "$query", "top_k": 3},
                output_key="search_hits",
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
                description="按 query 相关性排序命中并起草带引用回答",
                handler="draft_from_hits",
                depends_on=["search", "lookup_api"],
            ),
            Step(
                id="policy",
                kind=StepKind.POLICY,
                description="无依据拒答 / 引用校验",
                handler="apply_policy",
                depends_on=["draft"],
            ),
            Step(
                id="final",
                kind=StepKind.FINAL,
                description="定稿输出",
                handler="finalize",
                depends_on=["policy"],
            ),
        ],
    )


def register_builtin_workflows() -> None:
    register_workflow(build_docs_troubleshoot_workflow())
