"""Citation / refuse policy for docs troubleshoot."""
from __future__ import annotations

import re
from typing import Any


REFUSE_TEMPLATE = (
    "依据不足，无法给出确定结论。"
    "请补充报错原文、相关配置，或先调用 search_docs / lookup_api 检索后再答。"
)

PERSONAL_REFUSE_TEMPLATE = (
    "个人库中没有足够依据，无法给出确定结论。"
    "请先投递网页链接或粘贴文本入库，再针对个人收藏提问。"
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
    re.compile(r"https?://platform\.claude\.com/\S+", re.I),
    re.compile(r"https?://\S+", re.I),
)

_HTTP_URL_RE = re.compile(r"https?://[^\s,，\]\)\"']+", re.I)
_OFFICIAL_URL_RE = re.compile(r"https?://platform\.claude\.com/[^\s,，\]\)\"']+", re.I)
_FILE_SOURCE_RE = re.compile(r"([a-zA-Z0-9_\-./]+\.(?:md|json|ya?ml|txt))", re.I)


def _normalize_claimed_source(raw: str) -> str:
    text = (raw or "").strip().rstrip(".,;；。")
    if text.startswith("http://") or text.startswith("https://"):
        m = _HTTP_URL_RE.match(text)
        return m.group(0) if m else text
    m = _FILE_SOURCE_RE.search(text)
    if m:
        return m.group(1).split("/")[-1]
    return text


def extract_claimed_sources(answer: str) -> list[str]:
    """Extract sources from explicit citation markers (filenames or http(s) URLs)."""
    found: list[str] = []
    patterns = (
        re.compile(
            r"(?:来源|根据|\[source|source)\s*[:：\]]?\s*"
            r"(https?://[^\s,，\]\)]+|"
            r"[a-zA-Z0-9_\-./]+\.(?:md|json|ya?ml|txt))",
            re.I,
        ),
        re.compile(r"根据\s+([a-zA-Z0-9_\-./]+\.(?:md|json|ya?ml|txt))", re.I),
    )
    for pat in patterns:
        for m in pat.finditer(answer or ""):
            found.append(_normalize_claimed_source(m.group(1)))
    tail = re.search(r"来源\s*[:：]\s*(.+?)\s*$", answer or "", re.I | re.M)
    if tail:
        for part in re.split(r"[,，]", tail.group(1)):
            part = part.strip()
            url = _HTTP_URL_RE.search(part)
            if url:
                found.append(_normalize_claimed_source(url.group(0)))
                continue
            m2 = _FILE_SOURCE_RE.search(part)
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
        allowed: set[str] = set()
        for s in allowed_sources:
            raw = str(s or "").strip()
            if not raw:
                continue
            allowed.add(raw)
            if raw.startswith("http://") or raw.startswith("https://"):
                allowed.add(raw.rstrip("/"))
            else:
                allowed.add(raw.split("/")[-1])
        missing = [c for c in claimed if c not in allowed and c.rstrip("/") not in allowed]
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


def active_refuse_template() -> str:
    """Pick refuse copy for personal KB vs corpus/eval paths."""
    try:
        from react_agent.apps.docs_troubleshoot.docs_sources import uses_personal

        if uses_personal():
            return PERSONAL_REFUSE_TEMPLATE
    except Exception:  # noqa: BLE001 — policy must not fail closed on import issues
        pass
    return REFUSE_TEMPLATE


def enforce_answer_policy(
    answer: str,
    *,
    allowed_sources: list[str] | None = None,
    must_refuse: bool = False,
) -> dict[str, Any]:
    """Apply refuse-if-uncited (or force refuse) policy to a draft answer."""
    refuse_template = active_refuse_template()
    if must_refuse:
        text = (answer or "").strip()
        # Keep an explicit upstream refuse reason (e.g. Claude official fetch failure).
        refuse_answer = (
            text
            if text.startswith("依据不足") or text.startswith("个人库中没有足够依据")
            else refuse_template
        )
        return {
            "answer": refuse_answer,
            "refused": True,
            "policy": "forced_refuse",
            "citations": [],
        }
    check = verify_citations(answer, allowed_sources=allowed_sources)
    if not check["ok"]:
        return {
            "answer": refuse_template,
            "refused": True,
            "policy": check["reason"],
            "citations": [],
            "check": check,
        }
    cites = []
    for s in check["claimed_sources"]:
        item: dict[str, Any] = {"source": s, "snippet": ""}
        if str(s).startswith("http://") or str(s).startswith("https://"):
            item["url"] = s
        cites.append(item)
    return {
        "answer": answer,
        "refused": False,
        "policy": "ok",
        "citations": cites,
        "check": check,
    }
