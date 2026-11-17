"""Per-actor personal knowledge base (UI path; isolated from builtin corpus).

Persistence lives under the platform data directory (see ``runtime_dir``),
never inside the git tree. Ingest and search are scoped by actor id.
"""
from __future__ import annotations

import json
import re
import threading
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from react_agent.paths import runtime_dir
from react_agent.rag import RAG
from react_agent.safety.net_guard import open_validated, validate_url

MAX_TEXT_CHARS = 100_000
MAX_FETCH_BYTES = 200_000
FETCH_TIMEOUT = 10.0
MAX_ACTOR_LEN = 64

_actor_override: ContextVar[str | None] = ContextVar(
    "docs_troubleshoot_actor_id", default=None
)
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
_RAG_CACHE: dict[str, RAG] = {}


Fetcher = Callable[[str], tuple[bool, str, bytes]]


def set_actor_id(actor_id: str | None) -> Token:
    """Bind actor id for the current request/tool stack."""
    return _actor_override.set(normalize_actor_id(actor_id) if actor_id else None)


def reset_actor_id(token: Token) -> None:
    """Restore previous actor binding."""
    _actor_override.reset(token)


def current_actor_id() -> str | None:
    """Return the request-scoped actor id, if any."""
    return _actor_override.get()


def normalize_actor_id(raw: str | None) -> str:
    """Sanitize actor id for filesystem isolation (no path traversal)."""
    text = (raw or "").strip()
    if not text:
        raise ValueError("actor_id is required")
    if len(text) > MAX_ACTOR_LEN:
        raise ValueError(f"actor_id too long (max {MAX_ACTOR_LEN})")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", text):
        raise ValueError("actor_id must be alphanumeric (plus ._-)")
    if ".." in text or "/" in text or "\\" in text:
        raise ValueError("actor_id rejects path separators")
    return text


def personal_root() -> Path:
    """Root directory for all actors' personal stores."""
    path = runtime_dir(
        "docs-troubleshoot/personal",
        env_var="REACT_AGENT_PERSONAL_KB_DIR",
    )
    path.mkdir(parents=True, exist_ok=True)
    return path


def actor_dir(actor_id: str) -> Path:
    """Return the on-disk directory for one actor."""
    safe = normalize_actor_id(actor_id)
    path = personal_root() / safe
    path.mkdir(parents=True, exist_ok=True)
    return path


def _lock_for(actor_id: str) -> threading.RLock:
    key = normalize_actor_id(actor_id)
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[key] = lock
        return lock


def _sources_path(actor_id: str) -> Path:
    return actor_dir(actor_id) / "sources.json"


def _index_path(actor_id: str) -> Path:
    return actor_dir(actor_id) / "index_cache.json"


def _load_sources(actor_id: str) -> list[dict[str, Any]]:
    path = _sources_path(actor_id)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def _save_sources(actor_id: str, sources: list[dict[str, Any]]) -> None:
    path = _sources_path(actor_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(sources, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def get_actor_rag(actor_id: str) -> RAG:
    """Load (or create) the durable RAG index for one actor."""
    import os

    os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")
    safe = normalize_actor_id(actor_id)
    cached = _RAG_CACHE.get(safe)
    if cached is not None:
        return cached
    with _lock_for(safe):
        cached = _RAG_CACHE.get(safe)
        if cached is not None:
            return cached
        rag = RAG(save_path=str(_index_path(safe)))
        _RAG_CACHE[safe] = rag
        return rag


def clear_actor_cache(actor_id: str | None = None) -> None:
    """Drop in-process RAG cache (tests / reset)."""
    with _LOCKS_GUARD:
        if actor_id is None:
            _RAG_CACHE.clear()
            return
        _RAG_CACHE.pop(normalize_actor_id(actor_id), None)


def list_sources(actor_id: str) -> list[dict[str, Any]]:
    """List ingested sources for an actor (newest first)."""
    sources = _load_sources(actor_id)
    return list(reversed(sources))


def _strip_html(raw: str) -> tuple[str, str]:
    """Return (title, plain_text) from HTML or plain text."""
    title = ""
    m = re.search(r"<title[^>]*>(.*?)</title>", raw or "", re.I | re.S)
    if m:
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1))).strip()
    text = raw or ""
    if re.search(r"</?(html|body|p|div|h[1-6]|article)\b", text, re.I):
        text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
        text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
        text = re.sub(r"<[^>]+>", "\n", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return title, text


def _default_fetcher(url: str) -> tuple[bool, str, bytes]:
    return open_validated(
        url,
        timeout=FETCH_TIMEOUT,
        headers={
            "User-Agent": (
                "react-agent-personal-kb/0.1 "
                "(+https://github.com/weihuaguo270-ops/work-assistant)"
            )
        },
        max_bytes=MAX_FETCH_BYTES,
    )


def validate_ingest_url(url: str, *, resolve: bool = True) -> tuple[bool, str]:
    """Reject non-http(s), localhost, and private targets before fetch."""
    raw = (url or "").strip()
    if not raw:
        return False, "URL 为空"
    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme in ("file", "ftp", "data", "javascript"):
        return False, f"不支持的协议: {scheme}"
    host = (parsed.hostname or "").lower().rstrip(".")
    if host in ("localhost", "localhost.localdomain"):
        return False, f"不允许访问本机地址: {host}"
    return validate_url(raw, resolve=resolve)


def _remove_source_chunks(rag: RAG, source_key: str) -> None:
    if not rag.chunks:
        return
    kept_chunks: list[str] = []
    kept_sources: list[str] = []
    kept_vecs: list = []
    for chunk, src, vec in zip(rag.chunks, rag.sources, rag.vecs or []):
        if str(src) == source_key:
            continue
        kept_chunks.append(chunk)
        kept_sources.append(src)
        kept_vecs.append(vec)
    rag.chunks = kept_chunks
    rag.sources = kept_sources
    rag.vecs = kept_vecs


def ingest_text(
    actor_id: str,
    text: str,
    *,
    title: str = "",
    source_url: str = "",
    source_id: str | None = None,
) -> dict[str, Any]:
    """Clean, chunk, and persist pasted text into the actor's personal store."""
    safe = normalize_actor_id(actor_id)
    cleaned = (text or "").strip()
    if not cleaned:
        return {"ok": False, "error": "empty_text", "message": "文本为空"}
    if len(cleaned) > MAX_TEXT_CHARS:
        cleaned = cleaned[:MAX_TEXT_CHARS]

    display_title = (title or "").strip() or (
        source_url.strip() if source_url else "粘贴文本"
    )
    key = (source_id or source_url or f"paste:{display_title}")[:300]
    ingested_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    with _lock_for(safe):
        rag = get_actor_rag(safe)
        _remove_source_chunks(rag, key)
        before = len(rag.chunks)
        rag.ingest_text(cleaned, source=key)
        added = len(rag.chunks) - before
        # ingest_text skips disk write; personal store must survive restarts.
        rag._save()

        sources = [s for s in _load_sources(safe) if s.get("source_id") != key]
        record = {
            "source_id": key,
            "title": display_title,
            "url": source_url.strip() or "",
            "ingested_at": ingested_at,
            "chunk_count": added,
            "char_count": len(cleaned),
            "kind": "url" if source_url.strip() else "text",
        }
        sources.append(record)
        _save_sources(safe, sources)

    return {
        "ok": True,
        "actor_id": safe,
        "source": record,
        "chunk_count": added,
        "message": f"已入库 {added} 个片段",
    }


def ingest_url(
    actor_id: str,
    url: str,
    *,
    fetcher: Optional[Fetcher] = None,
    resolve: bool = True,
) -> dict[str, Any]:
    """Fetch a public http(s) page, extract text, and store under the actor."""
    ok, reason = validate_ingest_url(url, resolve=resolve)
    if not ok:
        return {"ok": False, "error": "invalid_url", "message": reason}

    fetch = fetcher or _default_fetcher
    try:
        fetched_ok, err_or_url, body = fetch(url.strip())
    except Exception as exc:  # noqa: BLE001 — surface as ingest failure
        return {
            "ok": False,
            "error": "fetch_failed",
            "message": f"抓取失败: {exc}"[:300],
        }
    if not fetched_ok:
        return {
            "ok": False,
            "error": "fetch_failed",
            "message": f"抓取失败: {err_or_url}"[:300],
        }

    raw = body.decode("utf-8", errors="replace")
    page_title, text = _strip_html(raw)
    if not text.strip():
        return {"ok": False, "error": "empty_body", "message": "页面无可提取正文"}

    return ingest_text(
        actor_id,
        text,
        title=page_title or url.strip(),
        source_url=url.strip(),
        source_id=url.strip(),
    )


def search_personal(
    actor_id: str,
    query: str,
    *,
    top_k: int = 3,
) -> dict[str, Any]:
    """Keyword/semantic search limited to one actor's personal store."""
    safe = normalize_actor_id(actor_id)
    rag = get_actor_rag(safe)
    process: list[dict[str, str]] = [
        {
            "step": "personal_kb",
            "detail": f"actor={safe} chunks={len(rag.chunks)} sources={len(_load_sources(safe))}",
        }
    ]
    if not rag.chunks:
        process.append(
            {
                "step": "personal_empty",
                "detail": "个人库为空；未使用内置演示语料",
            }
        )
        return {
            "ok": False,
            "message": "personal_kb_empty",
            "results": [],
            "docs_sources": ["personal"],
            "retrieval_process": process,
            "hint": "个人库中没有足够依据。请先投递网页链接或粘贴文本后再提问。",
        }

    hits = rag.query(query, top_k=top_k)
    process.append(
        {
            "step": "personal_search",
            "detail": f"keyword/semantic hits={len(hits)}",
        }
    )
    meta_by_id = {s.get("source_id"): s for s in _load_sources(safe)}
    results: list[dict[str, Any]] = []
    for h in hits:
        src = str(h.get("source") or "")
        meta = meta_by_id.get(src) or {}
        url = str(meta.get("url") or "")
        if not url and (src.startswith("http://") or src.startswith("https://")):
            url = src
        results.append(
            {
                "source": url or src,
                "title": meta.get("title") or src,
                "url": url,
                "score": h.get("score"),
                "content": str(h.get("content") or "")[:800],
                "docs_source": "personal",
            }
        )

    if not results:
        return {
            "ok": False,
            "message": "no_hits",
            "results": [],
            "docs_sources": ["personal"],
            "retrieval_process": process,
            "hint": "个人库中没有足够依据。可换个问法，或先投递相关资料。",
        }

    return {
        "ok": True,
        "results": results,
        "docs_sources": ["personal"],
        "retrieval_process": process,
    }
