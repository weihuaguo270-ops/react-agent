"""On-demand Claude official developer docs retrieval (platform.claude.com).

Flow: fetch ``/llms.txt`` → score title/summary → fetch only selected pages.
Full documentation is never written into the repository; only a short-lived
local cache (source URL + fetched_at) may be used under the runtime data dir.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from urllib import error as urlerror

from react_agent.apps.docs_troubleshoot.ranking import query_tokens
from react_agent.paths import runtime_dir
from react_agent.safety.net_guard import open_validated

LLMS_TXT_URL = "https://platform.claude.com/llms.txt"
DOCS_MCP_URL = "https://platform.claude.com/docs/mcp"
ALLOWED_HOSTS = frozenset({"platform.claude.com"})
DEFAULT_CACHE_TTL_SEC = 900
MAX_INDEX_BYTES = 2_000_000
MAX_PAGE_BYTES = 400_000
MAX_SELECTED_PAGES = 5

Fetcher = Callable[[str], tuple[bool, str, str]]


@dataclass(frozen=True)
class IndexEntry:
    title: str
    url: str
    summary: str = ""

    @property
    def blob(self) -> str:
        return f"{self.title} {self.summary} {self.url}".lower()


_LINK_RE = re.compile(
    r"^\s*[-*]\s*\[([^\]]+)\]\((https?://platform\.claude\.com/[^)\s]+)\)"
    r"(?:\s*[-–—:]\s*(.+))?\s*$",
    re.I,
)


def parse_llms_index(text: str) -> list[IndexEntry]:
    """Parse markdown bullet links from platform.claude.com/llms.txt."""
    entries: list[IndexEntry] = []
    seen: set[str] = set()
    for line in (text or "").splitlines():
        m = _LINK_RE.match(line)
        if not m:
            continue
        title = m.group(1).strip()
        url = m.group(2).strip()
        summary = (m.group(3) or "").strip()
        if url in seen:
            continue
        seen.add(url)
        entries.append(IndexEntry(title=title, url=url, summary=summary))
    return entries


def select_index_entries(
    entries: list[IndexEntry],
    query: str,
    *,
    top_k: int = MAX_SELECTED_PAGES,
) -> list[tuple[float, IndexEntry]]:
    """Score index rows by title/summary overlap; return top_k with scores."""
    tokens = query_tokens(query)
    ql = (query or "").lower()
    scored: list[tuple[float, IndexEntry]] = []
    for entry in entries:
        blob = entry.blob
        score = 0.0
        for tok in tokens:
            if tok in blob:
                score += 2.0 if tok in entry.title.lower() else 1.0
        # Prefer exact-ish phrase hits in title
        for phrase in re.findall(r"[a-zA-Z][a-zA-Z0-9_\-]{2,}", ql):
            if phrase in entry.title.lower():
                score += 1.5
        if score > 0:
            scored.append((score, entry))
    scored.sort(key=lambda x: (-x[0], x[1].title.lower()))
    return scored[: max(1, top_k)]


def _default_fetcher(url: str) -> tuple[bool, str, str]:
    """HTTP GET via SSRF guard; returns (ok, error_or_url, text)."""
    try:
        ok, info, body = open_validated(
            url,
            timeout=12.0,
            headers={"User-Agent": "work-assistant-docs-troubleshoot/1.0"},
            allow_hosts=ALLOWED_HOSTS,
            max_bytes=MAX_PAGE_BYTES if url != LLMS_TXT_URL else MAX_INDEX_BYTES,
        )
    except urlerror.HTTPError as exc:
        return False, f"HTTP {exc.code}", ""
    if not ok:
        return False, info, ""
    try:
        text = body.decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return False, str(exc), ""
    return True, info, text


def cache_root() -> Path:
    """Short-lived cache directory (outside the git worktree by default)."""
    override = os.environ.get("REACT_AGENT_CLAUDE_DOCS_CACHE_DIR")
    if override:
        path = Path(override).expanduser().resolve()
    else:
        path = runtime_dir("claude-docs-cache")
    path.mkdir(parents=True, exist_ok=True)
    # Marker so operators / tests can assert provenance without committing bodies.
    marker = path / "SOURCE.txt"
    if not marker.exists():
        marker.write_text(
            "Ephemeral Claude official docs cache.\n"
            f"Index: {LLMS_TXT_URL}\n"
            "Do not commit; not part of the repository corpus.\n",
            encoding="utf-8",
        )
    return path


def cache_ttl_sec() -> int:
    raw = os.environ.get("REACT_AGENT_CLAUDE_DOCS_CACHE_TTL", str(DEFAULT_CACHE_TTL_SEC))
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_CACHE_TTL_SEC


def _cache_key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]


def _read_cache(url: str) -> Optional[dict[str, Any]]:
    ttl = cache_ttl_sec()
    if ttl <= 0:
        return None
    path = cache_root() / f"{_cache_key(url)}.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    fetched_at = float(data.get("fetched_at_epoch") or 0)
    if fetched_at <= 0 or (time.time() - fetched_at) > ttl:
        return None
    if data.get("url") != url:
        return None
    return data


def _write_cache(url: str, title: str, text: str) -> dict[str, Any]:
    now = time.time()
    payload = {
        "url": url,
        "title": title,
        "source": "Claude 官方文档 (platform.claude.com)",
        "fetched_at": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        "fetched_at_epoch": now,
        "text": text[:MAX_PAGE_BYTES],
    }
    path = cache_root() / f"{_cache_key(url)}.json"
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return payload


def fetch_text(
    url: str,
    *,
    fetcher: Optional[Fetcher] = None,
    title: str = "",
    use_cache: bool = True,
) -> tuple[bool, str, dict[str, Any]]:
    """Fetch page text with optional short-lived cache."""
    if use_cache:
        cached = _read_cache(url)
        if cached:
            return True, "", cached
    fn = fetcher or _default_fetcher
    ok, info, text = fn(url)
    if not ok:
        return False, info or "fetch_failed", {}
    payload = _write_cache(url, title, text) if use_cache else {
        "url": url,
        "title": title,
        "source": "Claude 官方文档 (platform.claude.com)",
        "fetched_at": datetime.now(tz=timezone.utc).isoformat(),
        "fetched_at_epoch": time.time(),
        "text": text,
    }
    if not use_cache:
        payload["text"] = text
    return True, "", payload


def _strip_markdown_noise(text: str) -> str:
    # Keep enough prose for keyword ranking; drop huge code fences lightly.
    cleaned = re.sub(r"```.*?```", " ", text or "", flags=re.S)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def search_claude_official(
    query: str,
    *,
    top_k: int = 3,
    fetcher: Optional[Fetcher] = None,
    index_text: Optional[str] = None,
) -> dict[str, Any]:
    """Select related docs from llms.txt then fetch page bodies.

    Returns a tool-shaped dict with official URLs as ``source`` / ``url``.
    Never falls back to the built-in synthetic corpus.
    """
    process: list[dict[str, str]] = []
    fn = fetcher or _default_fetcher

    if index_text is None:
        process.append(
            {
                "step": "fetch_llms_index",
                "detail": f"GET {LLMS_TXT_URL}",
            }
        )
        ok, err, payload = fetch_text(
            LLMS_TXT_URL, fetcher=fn, title="llms.txt", use_cache=True
        )
        if not ok:
            return {
                "ok": False,
                "message": "claude_official_index_unavailable",
                "error": err or "llms.txt fetch failed",
                "results": [],
                "retrieval_process": process,
                "docs_source": "claude_official",
                "hint": (
                    "无法读取 Claude 官方文档索引 (platform.claude.com/llms.txt)。"
                    "未改用内置演示语料。"
                ),
            }
        index_text = str(payload.get("text") or "")
        process.append(
            {
                "step": "index_cached",
                "detail": f"fetched_at={payload.get('fetched_at', '')}",
            }
        )
    else:
        process.append({"step": "fetch_llms_index", "detail": "fixture/injected index"})

    entries = parse_llms_index(index_text)
    if not entries:
        return {
            "ok": False,
            "message": "claude_official_index_empty",
            "error": "no entries parsed from llms.txt",
            "results": [],
            "retrieval_process": process,
            "docs_source": "claude_official",
        }

    selected = select_index_entries(entries, query, top_k=max(top_k, 3))
    process.append(
        {
            "step": "select_from_index",
            "detail": ", ".join(
                f"{e.title} ({score:.1f})" for score, e in selected
            )
            or "(none)",
        }
    )
    if not selected:
        return {
            "ok": False,
            "message": "no_hits",
            "error": "no index entries matched the query",
            "results": [],
            "retrieval_process": process,
            "docs_source": "claude_official",
        }

    results: list[dict[str, Any]] = []
    for score, entry in selected[:top_k]:
        process.append(
            {
                "step": "fetch_page",
                "detail": f"{entry.title} → {entry.url}",
            }
        )
        ok, err, payload = fetch_text(
            entry.url, fetcher=fn, title=entry.title, use_cache=True
        )
        if not ok:
            process.append(
                {
                    "step": "fetch_page_failed",
                    "detail": f"{entry.url}: {err}",
                }
            )
            continue
        body = _strip_markdown_noise(str(payload.get("text") or ""))
        if not body:
            continue
        results.append(
            {
                "source": entry.url,
                "url": entry.url,
                "title": entry.title,
                "score": score,
                "content": body[:800],
                "fetched_at": payload.get("fetched_at"),
                "docs_source": "claude_official",
            }
        )

    if not results:
        return {
            "ok": False,
            "message": "claude_official_pages_unavailable",
            "error": "selected pages could not be fetched",
            "results": [],
            "retrieval_process": process,
            "docs_source": "claude_official",
            "hint": (
                "已从索引选出相关页，但正文拉取失败。"
                "未改用内置演示语料冒充 Claude 官方文档。"
            ),
        }

    return {
        "ok": True,
        "results": results,
        "retrieval_process": process,
        "docs_source": "claude_official",
        "mcp_hint": DOCS_MCP_URL,
    }
