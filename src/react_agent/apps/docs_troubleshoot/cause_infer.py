"""Infer candidate causes from retrieval hits + field evidence (generalizable)."""
from __future__ import annotations

import re
from typing import Any

from react_agent.apps.docs_troubleshoot.ranking import query_tokens

_ERROR_CODE_RE = re.compile(
    r"\b(unauthorized|rate_limited|invalid_request|webhook_disabled|"
    r"tool_timeout|missing_idempotency_key|upstream_timeout|internal_error)\b",
    re.I,
)
_HTTP_RE = re.compile(r"\b(?:HTTP\s*)?(401|409|429|400|410|500|502|504)\b", re.I)


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？.!?])\s*|\n+", text or "")
    return [p.strip() for p in parts if len(p.strip()) > 12]


def _field_signals(evidence_bundle: dict[str, Any]) -> tuple[set[str], set[int]]:
    codes: set[str] = set()
    statuses: set[int] = set()
    for item in evidence_bundle.get("items") or []:
        if item.get("type") == "http_error":
            if item.get("error_code"):
                codes.add(str(item["error_code"]).lower())
            sc = int(item.get("status_code") or 0)
            if sc:
                statuses.add(sc)
        if item.get("type") == "log_excerpt":
            blob = " ".join(item.get("highlights") or [])
            codes.update(c.lower() for c in _ERROR_CODE_RE.findall(blob))
            for m in _HTTP_RE.finditer(blob):
                statuses.add(int(m.group(1)))
        if item.get("type") == "trace_context":
            for span in item.get("spans") or []:
                if span.get("error"):
                    codes.add(str(span.get("error")).lower())
    return codes, statuses


def _sentence_aligns(sent: str, field_codes: set[str], field_status: set[int]) -> bool:
    sl = sent.lower()
    if field_codes and any(c in sl for c in field_codes):
        return True
    if field_status and any(str(s) in sent for s in field_status):
        return True
    return False


def infer_causes_from_retrieval(
    hits: list[dict[str, Any]],
    *,
    evidence_bundle: dict[str, Any],
    query: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Extract doc-backed causes; prefer sentences aligned with field evidence."""
    field_codes, field_status = _field_signals(evidence_bundle)
    tokens = query_tokens(query)
    scored: list[tuple[float, dict[str, Any]]] = []

    for hit in hits:
        src = str(hit.get("source") or "unknown")
        label = src.split("/")[-1]
        for sent in _split_sentences(str(hit.get("content") or "")):
            sl = sent.lower()
            score = sum(0.5 for t in tokens if t in sl)
            aligned = _sentence_aligns(sent, field_codes, field_status)
            if aligned:
                score += 3.0
            for code in _ERROR_CODE_RE.findall(sent):
                if code.lower() in field_codes:
                    score += 2.0
                elif field_codes:
                    score += 0.5
            if score <= 0 and not aligned:
                continue
            conf = "high" if aligned and score >= 3 else "medium" if score >= 1.5 else "low"
            scored.append(
                (
                    score,
                    {
                        "cause": sent[:220],
                        "confidence": conf,
                        "doc_hints": [label],
                        "source": "retrieval",
                        "aligned_field": aligned,
                    },
                )
            )

    scored.sort(key=lambda x: x[0], reverse=True)
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for _, cause in scored:
        key = cause["cause"][:80].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cause)
        if len(out) >= limit:
            break
    return out


def merge_causes(
    rule_causes: list[dict[str, Any]],
    doc_causes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Rules first (high confidence), then retrieval; dedupe by cause prefix."""
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()

    for c in rule_causes:
        key = str(c.get("cause", ""))[:80].lower()
        if key and key not in seen:
            seen.add(key)
            item = dict(c)
            item.setdefault("source", "rule")
            merged.append(item)

    for c in doc_causes:
        key = str(c.get("cause", ""))[:80].lower()
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(c)

    return merged[:8]


def field_doc_alignment(
    evidence_bundle: dict[str, Any],
    doc_causes: list[dict[str, Any]],
) -> bool:
    """返回现场字段是否得到至少一条文档根因证据支持。"""
    if not evidence_bundle.get("count"):
        return False
    return any(c.get("aligned_field") for c in doc_causes)
