"""Citation / refuse policy for docs troubleshoot."""
from __future__ import annotations

import re
from typing import Any


REFUSE_TEMPLATE = (
    "依据不足，无法给出确定结论。"
    "请补充报错原文、相关配置，或先调用 search_docs / lookup_api 检索后再答。"
)

REFUSE_QUERY_NEEDLES = (
    "股价",
    "涨到多少",
    "删库",
    "删除生产",
    "删掉生产",
    "生产数据库",
    "rm -rf",
    "drop table",
    "drop database",
    "绕过鉴权",
    "绕过 api key",
    "绕过api key",
    "后门",
    "bypass auth",
)


def should_refuse_query(query: str) -> bool:
    """Central refuse heuristic for out-of-domain or dangerous requests."""
    q = (query or "").lower()
    if any(k.lower() in q for k in REFUSE_QUERY_NEEDLES):
        return True
    if "绕过" in query and any(k in q for k in ("鉴权", "api key", "apikey", "认证")):
        return True
    return False

_SOURCE_PATTERNS = (
    re.compile(r"来源\s*[:：]\s*\S+", re.I),
    re.compile(r"\[source\s*:\s*[^\]]+\]", re.I),
    re.compile(r"\(source:\s*[^)]+\)", re.I),
    re.compile(r"根据\s+\S+\.(md|json|ya?ml)", re.I),
)


def extract_claimed_sources(answer: str) -> list[str]:
    """Extract sources from explicit citation markers (not every filename in text)."""
    found: list[str] = []
    patterns = (
        re.compile(
            r"(?:来源|根据|\[source|source)\s*[:：\]]?\s*"
            r"([a-zA-Z0-9_\-./]+\.(?:md|json|ya?ml|txt))",
            re.I,
        ),
        re.compile(r"根据\s+([a-zA-Z0-9_\-./]+\.(?:md|json|ya?ml|txt))", re.I),
    )
    for pat in patterns:
        for m in pat.finditer(answer or ""):
            found.append(m.group(1).split("/")[-1])
    tail = re.search(r"来源\s*[:：]\s*(.+?)\s*$", answer or "", re.I | re.M)
    if tail:
        for part in re.split(r"[,，]", tail.group(1)):
            part = part.strip()
            m2 = re.search(r"([a-zA-Z0-9_\-./]+\.(?:md|json|ya?ml|txt))", part, re.I)
            if m2:
                found.append(m2.group(1).split("/")[-1])
    return list(dict.fromkeys(found))


def answer_has_citation_marker(answer: str) -> bool:
    """返回答案是否含受支持的显式引用标记。"""
    text = answer or ""
    if any(p.search(text) for p in _SOURCE_PATTERNS):
        return True
    return bool(extract_claimed_sources(text))


def verify_citations(
    answer: str,
    allowed_sources: list[str] | None = None,
) -> dict[str, Any]:
    """
    Check that the answer cites sources; optionally that cited files are in allowed set.

    Returns: {ok, reason, claimed_sources, missing}
    """
    claimed = extract_claimed_sources(answer)
    if not answer_has_citation_marker(answer) and not claimed:
        return {
            "ok": False,
            "reason": "no_citation",
            "claimed_sources": [],
            "missing": [],
            "hint": REFUSE_TEMPLATE,
        }
    if allowed_sources is not None:
        allowed = {s.split("/")[-1] for s in allowed_sources}
        missing = [c for c in claimed if c not in allowed]
        if claimed and missing:
            return {
                "ok": False,
                "reason": "unknown_source",
                "claimed_sources": claimed,
                "missing": missing,
                "hint": REFUSE_TEMPLATE,
            }
    return {
        "ok": True,
        "reason": "ok",
        "claimed_sources": claimed,
        "missing": [],
        "hint": "",
    }


def enforce_answer_policy(
    answer: str,
    *,
    allowed_sources: list[str] | None = None,
    must_refuse: bool = False,
) -> dict[str, Any]:
    """Apply refuse-if-uncited (or force refuse) policy to a draft answer."""
    if must_refuse:
        return {
            "answer": REFUSE_TEMPLATE,
            "refused": True,
            "policy": "forced_refuse",
            "citations": [],
        }
    check = verify_citations(answer, allowed_sources=allowed_sources)
    if not check["ok"]:
        return {
            "answer": REFUSE_TEMPLATE,
            "refused": True,
            "policy": check["reason"],
            "citations": [],
            "check": check,
        }
    cites = [{"source": s, "snippet": ""} for s in check["claimed_sources"]]
    return {
        "answer": answer,
        "refused": False,
        "policy": "ok",
        "citations": cites,
        "check": check,
    }
