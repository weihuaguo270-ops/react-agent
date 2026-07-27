"""Shared retrieval ranking and draft builder for docs troubleshoot.

Uses sentence-level synthesis from ranked hits plus optional field-evidence
summary. Root-cause playbooks live in diagnosis.py / cause_rules.py.
See docs/EVIDENCE_DOCS_TROUBLESHOOT.md for product boundaries and roadmap.
"""
from __future__ import annotations

import json
import re
from typing import Any

from react_agent.apps.docs_troubleshoot.policy import should_refuse_query
from react_agent.apps.docs_troubleshoot.ranking import rank_with_evidence
from react_agent.apps.docs_troubleshoot.synthesize import (
    summarize_field_evidence,
    synthesize_draft,
)


def as_results(blob: Any) -> list[dict[str, Any]]:
    if isinstance(blob, str):
        try:
            blob = json.loads(blob)
        except json.JSONDecodeError:
            return []
    if isinstance(blob, dict):
        results = blob.get("results") or []
        return results if isinstance(results, list) else []
    return []


_HTTP_CODES = re.compile(r"\b(400|401|404|429|500)\b")
_MULTI_HINT = re.compile(
    r"几次|多少|最大值|默认|重试|超时秒|鉴权|Sunset|OPTIONS|tool_timeout|limit|预检|CORS|幂等|409|Idempotency"
)


def needs_multi_doc(query: str) -> bool:
    ql = query or ""
    codes = set(_HTTP_CODES.findall(ql))
    if len(codes) >= 2:
        return True
    if any(k in ql for k in ("分别", "都提到", "对比", "区别")) and len(codes) >= 2:
        return True
    if re.search(r"401.*429|429.*401", ql):
        return True
    if "和" in ql and len(codes) >= 2:
        return True
    return False


def _pick_unique_by_source(
    ranked: list[dict[str, Any]], limit: int
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen_sources: set[str] = set()
    for r in ranked:
        src = str(r.get("source") or "")
        if src in seen_sources:
            continue
        selected.append(r)
        seen_sources.add(src)
        if len(selected) >= limit:
            break
    return selected


def select_hits(ranked: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    if not ranked:
        return []
    ql = query or ""
    if "不要猜" in ql or ("不要" in ql and "别的" in ql):
        return ranked[:1]
    if needs_multi_doc(query):
        selected = _pick_unique_by_source(ranked, 3)
        return selected or ranked[:1]
    if _MULTI_HINT.search(ql):
        top_src = str(ranked[0].get("source") or "")
        same_source = [r for r in ranked if str(r.get("source") or "") == top_src][:3]
        if len(same_source) >= 2:
            return same_source
        selected = _pick_unique_by_source(ranked, 2)
        return selected or ranked[:1]
    return ranked[:1]


def build_draft_from_hits(
    query: str,
    search_hits: Any,
    api_hits: Any,
    evidence_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build draft + policy hints from retrieval blobs."""
    if should_refuse_query(query):
        return {
            "draft": "依据不足，无法给出确定结论。",
            "allowed_sources": [],
            "need_refuse": True,
        }

    merged = as_results(search_hits) + as_results(api_hits)
    seen: set[str] = set()
    uniq: list[dict[str, Any]] = []
    for r in merged:
        key = f"{r.get('source')}|{(r.get('content') or '')[:80]}"
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)

    ranked = rank_with_evidence(uniq, query, evidence_bundle)
    if not ranked:
        return {
            "draft": "未检索到相关文档。",
            "allowed_sources": [],
            "need_refuse": True,
        }

    top = select_hits(ranked, query)
    field_summary = summarize_field_evidence(evidence_bundle or {})
    draft, sources = synthesize_draft(query, top, field_summary=field_summary)
    if not draft:
        return {
            "draft": "未检索到相关文档。",
            "allowed_sources": [],
            "need_refuse": True,
        }
    return {
        "draft": draft,
        "allowed_sources": list(dict.fromkeys(sources)),
        "need_refuse": False,
        "ranked_sources": sources,
    }
