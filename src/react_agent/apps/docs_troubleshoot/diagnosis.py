"""Structured diagnosis output (P2 + rules + retrieval inference)."""
from __future__ import annotations

from typing import Any

from react_agent.apps.docs_troubleshoot.cause_infer import (
    field_doc_alignment,
    infer_causes_from_retrieval,
    merge_causes,
)
from react_agent.apps.docs_troubleshoot.cause_rules import (
    aggregate_from_rules,
    evidence_sufficiency,
    match_cause_rules,
)
from react_agent.apps.docs_troubleshoot.fix_policy import gate_fix_steps


def build_diagnosis(
    *,
    query: str,
    evidence_bundle: dict[str, Any],
    draft: str,
    ranked_sources: list[str] | None,
    refused: bool,
    retrieval_hits: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build structured diagnosis from docs draft + field evidence + retrieval."""
    phenomenon = query
    for item in evidence_bundle.get("items") or []:
        if item.get("type") == "http_error":
            http_status = int(item.get("status_code") or 0)
            error_code = str(item.get("error_code") or "")
            msg = item.get("message") or ""
            if msg:
                phenomenon = (
                    f"{query}（现场：HTTP {http_status} / {error_code}: {msg}）"
                )
        elif item.get("type") == "log_excerpt" and item.get("trace_id"):
            phenomenon = f"{query}（日志 trace_id={item.get('trace_id')}）"
        elif item.get("type") == "trace_context" and item.get("trace_id"):
            phenomenon = f"{query}（Trace {item.get('trace_id')}）"

    rules = match_cause_rules(query=query, evidence_bundle=evidence_bundle)
    agg = aggregate_from_rules(rules)
    doc_causes = infer_causes_from_retrieval(
        retrieval_hits or [],
        evidence_bundle=evidence_bundle,
        query=query,
    )
    aligned = field_doc_alignment(evidence_bundle, doc_causes)
    candidate_causes = merge_causes(list(agg.get("causes") or []), doc_causes)

    if not candidate_causes and ranked_sources:
        candidate_causes.append(
            {
                "cause": "需对照检索到的 Runbook / API 文档",
                "confidence": "medium",
                "doc_hints": list(ranked_sources)[:3],
                "source": "fallback",
            }
        )

    evidence_rows: list[dict[str, Any]] = []
    for item in evidence_bundle.get("items") or []:
        evidence_rows.append({"kind": "field", "detail": item})
    for src in ranked_sources or []:
        evidence_rows.append({"kind": "document", "source": src})

    verify_actions = list(agg.get("verify_actions") or [])
    if not verify_actions:
        verify_actions = [
            "核对 HTTP 状态码与 error.code 是否与文档一致",
            "检查 Authorization 头是否包含 Bearer API Key",
            "用 search_docs / lookup_api 交叉验证 Runbook 条目",
        ]
    if any(i.get("type") == "log_excerpt" for i in evidence_bundle.get("items") or []):
        verify_actions.append("用 trace_id / request_id 在日志平台过滤完整请求链")
    if any(i.get("type") == "trace_context" for i in evidence_bundle.get("items") or []):
        verify_actions.append("对照 Trace 中 error span 与服务边界")

    fix_steps_raw: list[str] = list(agg.get("fix_steps") or [])
    fix_steps, blocked_fix, pending_fix = gate_fix_steps(fix_steps_raw)
    risks: list[str] = ["在未确认根因前不要执行破坏性操作"]
    if blocked_fix:
        risks.append("已拦截不建议的修复步骤，请仅执行文档允许的只读排查")
    if pending_fix:
        risks.append(
            f"{len(pending_fix)} 条修复步骤需经权限闸门/HITL 确认后方可执行"
        )
    escalation = "若文档与现场证据矛盾，或涉及生产数据，升级至 on-call / SRE。"

    if refused:
        fix_steps = []
        blocked_fix = []
        pending_fix = []
        verify_actions = ["补充完整报错 JSON、Request-Id、日志片段或 Trace 后再诊断"]

    answer_summary = draft if not refused else "依据不足，无法给出确定结论。"
    sufficiency = evidence_sufficiency(
        evidence_bundle,
        rules,
        doc_causes=doc_causes,
        field_doc_aligned=aligned,
    )

    return {
        "phenomenon": phenomenon,
        "candidate_causes": candidate_causes,
        "evidence": evidence_rows,
        "verify_actions": verify_actions,
        "fix_steps": fix_steps,
        "pending_fix_steps": pending_fix,
        "blocked_fix_steps": blocked_fix,
        "fix_steps_gated": bool(blocked_fix or pending_fix),
        "risks": risks,
        "escalation": escalation,
        "answer_summary": answer_summary,
        "refused": refused,
        "citations": [{"source": s} for s in (ranked_sources or [])],
        "evidence_sufficiency": sufficiency,
        "field_doc_aligned": aligned,
        "matched_rules": [r.get("id") for r in rules if r.get("id")],
        "inferred_from_docs": sum(1 for c in doc_causes if c.get("source") == "retrieval"),
    }


def diagnosis_to_answer_text(diagnosis: dict[str, Any]) -> str:
    """Human-readable answer preserving citation line from draft/summary."""
    return str(diagnosis.get("answer_summary") or "")
