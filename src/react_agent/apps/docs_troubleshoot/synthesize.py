"""Structured draft synthesis from ranked retrieval hits."""
from __future__ import annotations

import re
from typing import Any

from react_agent.apps.docs_troubleshoot.ranking import query_tokens


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？.!?])\s*|\n+", text or "")
    return [p.strip() for p in parts if p.strip()]


def extract_relevant_sentences(content: str, query: str, *, limit: int = 2) -> list[str]:
    tokens = query_tokens(query)
    scored: list[tuple[float, str]] = []
    for sent in _split_sentences(content):
        sl = sent.lower()
        score = sum(1.0 for t in tokens if t in sl)
        if re.search(r"\b(400|401|404|429|500)\b", query):
            score += sum(
                0.5
                for c in re.findall(r"\b(400|401|404|429|500)\b", query)
                if c in sent
            )
        if re.search(r"\d+", query):
            score += 0.75 * len(re.findall(r"\d+", sent))
        for kw in ("OPTIONS", "Sunset", "Bearer", "tool_timeout", "无需鉴权", "重试"):
            if kw.lower() in query.lower() and kw.lower() in sl:
                score += 2.0
        if re.search(r"HTTP\s*方法|什么方法", query, re.I) and "options" in sl:
            score += 4.0
        if score > 0:
            scored.append((score, sent[:320]))
    scored.sort(key=lambda x: x[0], reverse=True)
    if scored:
        return [s for _, s in scored[:limit]]
    compact = (content or "").replace("\n", " ")[:320]
    return [compact] if compact else []


def synthesize_draft(
    query: str,
    hits: list[dict[str, Any]],
    *,
    field_summary: str = "",
) -> tuple[str, list[str]]:
    """Return (draft_text, source_list)."""
    sections: list[str] = []
    sources: list[str] = []
    seen_labels: set[str] = set()

    if field_summary:
        sections.append(f"【现场证据】{field_summary}")

    for r in hits:
        src = str(r.get("source") or "unknown")
        label = src.split("/")[-1]
        content = str(r.get("content") or "")
        sents = extract_relevant_sentences(content, query, limit=3)
        if not sents:
            continue
        if label not in seen_labels:
            sources.append(label)
            seen_labels.add(label)
        bullet = "；".join(sents)
        sections.append(f"【文档要点·{label}】{bullet}")

    if not sections:
        return "", []

    cite = ", ".join(dict.fromkeys(sources))
    body = " ".join(sections)
    return f"{body} 来源: {cite}", list(dict.fromkeys(sources))


def summarize_field_evidence(evidence_bundle: dict[str, Any]) -> str:
    parts: list[str] = []
    auth_relevant = False
    for item in evidence_bundle.get("items") or []:
        if item.get("type") == "http_error":
            sc = int(item.get("status_code") or 0)
            if sc == 401:
                auth_relevant = True
            parts.append(
                f"HTTP {item.get('status_code')} / {item.get('error_code')}: "
                f"{item.get('message', '')[:120]}"
            )
        elif item.get("type") == "request_headers":
            hdrs = item.get("headers") or {}
            if auth_relevant or any(k.lower() == "authorization" for k in hdrs):
                if item.get("has_authorization"):
                    parts.append("请求含 Authorization 头")
                else:
                    parts.append("请求未见有效 Authorization")
            elif any(k.lower() == "origin" for k in hdrs):
                parts.append("请求含 Origin（CORS 预检场景）")
        elif item.get("type") == "health_probe" and item.get("ok"):
            parts.append(f"health {item.get('status_code')} @ {item.get('url', '')[:60]}")
        elif item.get("type") == "log_excerpt":
            tid = item.get("trace_id") or ""
            n = len(item.get("highlights") or [])
            parts.append(f"日志 {n} 条关键行" + (f" trace_id={tid}" if tid else ""))
        elif item.get("type") == "trace_context":
            parts.append(
                f"Trace {item.get('trace_id') or '?'} "
                f"({item.get('error_span_count', 0)} error spans)"
            )
    return "；".join(parts)
