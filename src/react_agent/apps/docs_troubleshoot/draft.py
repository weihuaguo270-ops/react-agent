"""Shared retrieval ranking and draft builder for docs troubleshoot.

Current behavior: concatenate short corpus snippets (~280 chars per hit) with
citation markers. Does not synthesize root causes or diagnostic playbooks.
See docs/EVIDENCE_DOCS_TROUBLESHOOT.md for product boundaries and roadmap.
"""
from __future__ import annotations

import json
import re
from typing import Any

from react_agent.apps.docs_troubleshoot.policy import should_refuse_query


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


def query_tokens(query: str) -> list[str]:
    parts = re.findall(r"[A-Za-z0-9_./=\-]{2,}|[\u4e00-\u9fff]{2,}", query or "")
    return [p.lower() for p in parts]


def rank_results(results: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    tokens = query_tokens(query)
    if not results:
        return []
    boosts: list[str] = []
    ql = (query or "").lower()
    if "health" in ql or "鉴权" in query:
        boosts += ["health", "无需鉴权"]
    if "rag" in ql or "ci" in ql:
        boosts += ["rag_mode", "keyword", "react_agent_rag_mode"]
    if "mcp" in ql:
        boosts += ["disable_mcp", "mcp_mock"]
    if "invalid_request" in ql or "invalid cursor" in ql or "cursor" in ql:
        boosts += ["invalid_request", "400", "cursor"]
    if "错误码" in query or "error code" in ql:
        boosts += ["api_errors", "unauthorized", "rate_limited", "not_found"]
    if "permission" in ql or "权限闸门" in query or "permission gate" in ql:
        boosts += ["permission_gate", "deny", "confirm"]
    if "format b" in ql or "轨迹" in query or "schema" in ql:
        boosts += ["harness_trajectory", "format b"]
    if "429" in ql or "速率" in query:
        boosts += ["rate_limited", "429"]
    if "401" in ql or "authorization" in ql or "bearer" in ql or "unauthorized" in ql:
        boosts += ["401", "unauthorized", "authorization", "bearer"]
    if "pagination" in ql or "分页" in query or "limit" in ql:
        boosts += ["limit", "cursor", "pagination"]
    if "webhook" in ql:
        boosts += ["webhook", "hmac", "signature", "410"]
    if "cors" in ql or "跨域" in query or "预检" in query:
        boosts += ["options", "access-control", "cors_origins"]
    if "timeout" in ql or "超时" in query or "toolguard" in ql:
        boosts += ["tool_timeout", "react_agent_tool_timeout", "30"]
    if "version" in ql or "版本" in query or "sunset" in ql or "/v2" in query:
        boosts += ["sunset", "/v1", "/v2", "2027"]

    def score(r: dict[str, Any]) -> float:
        text = f"{r.get('source','')} {r.get('content','')}".lower()
        src = (r.get("source") or "").lower()
        hit = sum(1 for t in tokens if t in text)
        hit += 1.5 * sum(1 for b in boosts if b in text)
        if ("错误码" in query or "invalid_request" in ql) and "api_errors" in src:
            hit += 4.0
        if "cursor" not in ql and "分页" not in query and "pagination" in src:
            hit -= 1.5
        return hit + 0.01 * float(r.get("score") or 0)

    return sorted(results, key=score, reverse=True)


_HTTP_CODES = re.compile(r"\b(400|401|404|429|500)\b")


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


def select_hits(ranked: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    if not ranked:
        return []
    if not needs_multi_doc(query):
        return ranked[:1]
    selected: list[dict[str, Any]] = []
    seen_sources: set[str] = set()
    for r in ranked:
        src = str(r.get("source") or "")
        if src in seen_sources:
            continue
        selected.append(r)
        seen_sources.add(src)
        if len(selected) >= 3:
            break
    return selected or ranked[:1]


def build_draft_from_hits(
    query: str,
    search_hits: Any,
    api_hits: Any,
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

    ranked = rank_results(uniq, query)
    if not ranked:
        return {
            "draft": "未检索到相关文档。",
            "allowed_sources": [],
            "need_refuse": True,
        }

    top = select_hits(ranked, query)
    sources = [r.get("source", "") for r in top if r.get("source")]
    parts = []
    for r in top:
        src = r.get("source") or "unknown"
        snippet = (r.get("content") or "").replace("\n", " ")[:280]
        parts.append(f"根据 {src}：{snippet}")
    cite = ", ".join(sources)
    draft = " ".join(parts) + f" 来源: {cite}"
    return {
        "draft": draft,
        "allowed_sources": list(dict.fromkeys(sources)),
        "need_refuse": False,
        "ranked_sources": sources,
    }
