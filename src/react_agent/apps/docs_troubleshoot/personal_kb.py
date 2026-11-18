"""Per-actor personal knowledge base as documents (原文 / 摘要 / Agent 文稿).

Primary unit is one document: title, body (original or generated text), summary,
optional source URL or filename. Keywords remain internal search metadata — not
the product surface.

Persistence lives under ``runtime_dir`` (never in the git tree).
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import threading
import uuid
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from react_agent.paths import runtime_dir
from react_agent.safety.net_guard import open_validated, validate_url

MAX_TEXT_CHARS = 100_000
MAX_FETCH_BYTES = 200_000
FETCH_TIMEOUT = 10.0
MAX_ACTOR_LEN = 64
MAX_SUMMARY_CHARS = 800
MAX_KEYWORDS = 12
# Merge when keyword sets overlap strongly (no clustering).
KEYWORD_MERGE_JACCARD = 0.5
KEYWORD_MERGE_MIN_INTERSECTION = 2
MAX_UPLOAD_BYTES = 2_000_000

_actor_override: ContextVar[str | None] = ContextVar(
    "docs_troubleshoot_actor_id", default=None
)
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()

Fetcher = Callable[[str], tuple[bool, str, bytes]]
DocumentGenerator = Callable[..., dict[str, Any]]
# Back-compat alias
BookmarkGenerator = DocumentGenerator

_STOPWORDS = frozenset(
    {
        "的",
        "了",
        "和",
        "是",
        "在",
        "与",
        "及",
        "或",
        "等",
        "对",
        "为",
        "有",
        "把",
        "被",
        "从",
        "到",
        "一个",
        "以及",
        "可以",
        "进行",
        "使用",
        "如果",
        "以及",
        "the",
        "and",
        "for",
        "with",
        "this",
        "that",
        "from",
        "into",
        "your",
        "are",
        "was",
        "were",
    }
)


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


def _documents_path(actor_id: str) -> Path:
    return actor_dir(actor_id) / "documents.json"


def _bookmarks_path(actor_id: str) -> Path:
    """Legacy filename used by earlier personal-KB cuts."""
    return actor_dir(actor_id) / "bookmarks.json"


def _legacy_sources_path(actor_id: str) -> Path:
    return actor_dir(actor_id) / "sources.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _public_document(record: dict[str, Any]) -> dict[str, Any]:
    """Return UI-safe document fields (body truncated in list views)."""
    return {
        "id": record.get("id") or "",
        "title": record.get("title") or "",
        "summary": record.get("summary") or "",
        "keywords": list(record.get("keywords") or []),
        "url": record.get("url") or "",
        "filename": record.get("filename") or "",
        "requirement": record.get("requirement") or "",
        "kind": record.get("kind") or "text",
        "draft": bool(record.get("draft")),
        "ingested_at": record.get("ingested_at") or "",
        "updated_at": record.get("updated_at") or "",
        "merged_from": record.get("merged_from") or "",
        "char_count": int(record.get("char_count") or 0),
    }


# Back-compat name
_public_bookmark = _public_document


def clear_actor_cache(actor_id: str | None = None) -> None:
    """Compatibility no-op for tests that cleared the old RAG cache."""
    return None


def _normalize_record(item: dict[str, Any]) -> dict[str, Any]:
    """Ensure a stored record has document fields."""
    body = str(item.get("body") or item.get("content") or "")
    url = str(item.get("url") or "")
    filename = str(item.get("filename") or "")
    kind = str(item.get("kind") or "")
    if not kind:
        if url:
            kind = "url"
        elif filename.lower().endswith(".pdf"):
            kind = "pdf"
        elif filename:
            kind = "file"
        else:
            kind = "text"
    return {
        "id": str(item.get("id") or item.get("source_id") or _new_id()),
        "title": str(item.get("title") or "未命名文档")[:120],
        "summary": str(item.get("summary") or ""),
        "keywords": list(item.get("keywords") or []),
        "url": url,
        "filename": filename,
        "body": body,
        "requirement": str(item.get("requirement") or ""),
        "kind": kind,
        "draft": bool(item.get("draft", True)),
        "ingested_at": item.get("ingested_at") or _now(),
        "updated_at": item.get("updated_at") or item.get("ingested_at") or _now(),
        "char_count": int(item.get("char_count") or len(body)),
        "merged_from": str(item.get("merged_from") or ""),
    }


def _load_documents(actor_id: str) -> list[dict[str, Any]]:
    for path in (_documents_path(actor_id), _bookmarks_path(actor_id)):
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    docs = [_normalize_record(x) for x in data if isinstance(x, dict)]
                    if path.name == "bookmarks.json" and docs:
                        _save_documents(actor_id, docs)
                    return docs
            except (json.JSONDecodeError, OSError):
                pass
    # One-shot migrate from early sources.json if present.
    legacy = _legacy_sources_path(actor_id)
    if legacy.is_file():
        try:
            raw = json.loads(legacy.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            raw = []
        migrated: list[dict[str, Any]] = []
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                body = str(item.get("body") or item.get("content") or "")
                title = str(item.get("title") or "未命名文档")
                url = str(item.get("url") or "")
                fields = draft_document_fields(body or title, title_hint=title, requirement="")
                migrated.append(
                    {
                        "id": str(item.get("id") or item.get("source_id") or _new_id()),
                        "title": fields["title"],
                        "summary": fields["summary"],
                        "keywords": fields["keywords"],
                        "url": url,
                        "filename": "",
                        "body": body,
                        "requirement": "",
                        "kind": item.get("kind") or ("url" if url else "text"),
                        "draft": True,
                        "ingested_at": item.get("ingested_at") or _now(),
                        "updated_at": item.get("ingested_at") or _now(),
                        "char_count": len(body),
                        "merged_from": "",
                    }
                )
        if migrated:
            _save_documents(actor_id, migrated)
            return migrated
    return []


_load_bookmarks = _load_documents


def _save_documents(actor_id: str, documents: list[dict[str, Any]]) -> None:
    path = _documents_path(actor_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(documents, ensure_ascii=False, indent=2), encoding="utf-8"
    )


_save_bookmarks = _save_documents


def list_documents(actor_id: str) -> list[dict[str, Any]]:
    """List documents for an actor (newest first)."""
    items = _load_documents(actor_id)
    return [_public_document(b) for b in reversed(items)]


list_bookmarks = list_documents


def list_sources(actor_id: str) -> list[dict[str, Any]]:
    return list_documents(actor_id)


def get_document(actor_id: str, document_id: str) -> dict[str, Any] | None:
    """Return one document including full body for citation / edit."""
    safe = normalize_actor_id(actor_id)
    for item in _load_documents(safe):
        if str(item.get("id")) == str(document_id):
            out = _public_document(item)
            out["body"] = item.get("body") or ""
            return out
    return None


get_bookmark = get_document


def _new_id() -> str:
    return f"doc_{uuid.uuid4().hex[:12]}"


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


def extract_pdf_text(data: bytes) -> str:
    """Extract plain text from a PDF (pypdf if present, else stream heuristic)."""
    if not data:
        return ""
    try:
        from pypdf import PdfReader  # type: ignore
        import io

        reader = PdfReader(io.BytesIO(data))
        parts = []
        for page in reader.pages:
            try:
                parts.append(page.extract_text() or "")
            except Exception:  # noqa: BLE001
                continue
        text = "\n".join(parts).strip()
        if text:
            return text
    except Exception:  # noqa: BLE001 — optional dependency / parse failure
        pass

    # Lightweight fallback: pull literal strings near Tj / TJ operators.
    try:
        raw = data.decode("latin-1", errors="ignore")
    except Exception:  # noqa: BLE001
        return ""
    chunks: list[str] = []
    for m in re.finditer(r"\((?:\\.|[^\\)]){1,400}\)(?:\s*Tj|\s*TJ)", raw):
        lit = m.group(0)
        lit = re.sub(r"\)\s*T[jJ]$", "", lit)
        if lit.startswith("("):
            lit = lit[1:]
        lit = lit.replace("\\n", "\n").replace("\\r", "").replace("\\t", " ")
        lit = lit.replace("\\(", "(").replace("\\)", ")").replace("\\\\", "\\")
        lit = re.sub(r"\\[0-7]{1,3}", " ", lit)
        if lit.strip():
            chunks.append(lit)
    text = "\n".join(chunks)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def decode_upload_payload(
    *,
    filename: str = "",
    content_base64: str = "",
    text: str = "",
    content_type: str = "",
) -> dict[str, Any]:
    """Decode a local file / PDF upload into plain text for ingest."""
    name = (filename or "").strip()
    ctype = (content_type or "").lower()
    b64 = (content_base64 or "").strip()
    pasted = (text or "").strip()

    if b64:
        try:
            raw = base64.b64decode(b64, validate=False)
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "error": "invalid_upload",
                "message": f"无法解码文件内容: {exc}"[:200],
            }
        if len(raw) > MAX_UPLOAD_BYTES:
            return {
                "ok": False,
                "error": "too_large",
                "message": f"文件过大（上限 {MAX_UPLOAD_BYTES} 字节）",
            }
        is_pdf = (
            name.lower().endswith(".pdf")
            or "pdf" in ctype
            or raw[:5] == b"%PDF-"
        )
        if is_pdf:
            body = extract_pdf_text(raw)
            if not body.strip():
                return {
                    "ok": False,
                    "error": "empty_body",
                    "message": "无法从 PDF 提取正文",
                }
            return {
                "ok": True,
                "text": body,
                "filename": name or "upload.pdf",
                "kind": "pdf",
            }
        try:
            body = raw.decode("utf-8")
        except UnicodeDecodeError:
            body = raw.decode("utf-8", errors="replace")
        if not body.strip():
            return {"ok": False, "error": "empty_body", "message": "文件无正文"}
        return {
            "ok": True,
            "text": body,
            "filename": name or "upload.txt",
            "kind": "file",
        }

    if pasted:
        kind = "pdf" if name.lower().endswith(".pdf") else ("file" if name else "text")
        return {"ok": True, "text": pasted, "filename": name, "kind": kind}

    return {
        "ok": False,
        "error": "empty_input",
        "message": "请提供链接、正文或本地文件",
    }


def _tokenize(text: str) -> list[str]:
    """Lightweight tokens: English words + Chinese bigrams + digits."""
    raw = (text or "").lower()
    words = re.findall(r"[a-z0-9][a-z0-9\-_]{1,}", raw)
    zh = re.findall(r"[\u4e00-\u9fff]+", text or "")
    grams: list[str] = []
    for run in zh:
        if len(run) == 1:
            grams.append(run)
        else:
            grams.extend(run[i : i + 2] for i in range(len(run) - 1))
    out: list[str] = []
    for t in words + grams:
        if t in _STOPWORDS or len(t) < 2:
            continue
        if t not in out:
            out.append(t)
    return out


def _normalize_keywords(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = re.split(r"[,，、;\s]+", raw)
    elif isinstance(raw, (list, tuple)):
        parts = [str(x) for x in raw]
    else:
        parts = [str(raw)]
    out: list[str] = []
    for p in parts:
        p = p.strip()
        if not p or p in out:
            continue
        out.append(p[:40])
        if len(out) >= MAX_KEYWORDS:
            break
    return out


def draft_document_fields(
    body: str,
    *,
    title_hint: str = "",
    requirement: str = "",
) -> dict[str, Any]:
    """Offline draft generator: title + summary (+ internal keywords)."""
    text = (body or "").strip()
    title = (title_hint or "").strip()
    if not title:
        first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
        title = first_line[:60] if first_line else "未命名文档"
    title = title[:120]

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    sentences = re.split(r"(?<=[。！？.!?])\s*", text)
    sentences = [s.strip() for s in sentences if s.strip()]
    req = (requirement or "").strip()
    picked: list[str] = []
    if req:
        req_tokens = _tokenize(req)
        scored = []
        for s in sentences:
            score = sum(1 for t in req_tokens if t in s.lower() or t in s)
            if score:
                scored.append((score, s))
        scored.sort(key=lambda x: x[0], reverse=True)
        picked = [s for _, s in scored[:3]]
    if not picked:
        if paragraphs:
            picked = paragraphs[:2]
        else:
            picked = sentences[:3] or ([text[:MAX_SUMMARY_CHARS]] if text else [])
    summary = " ".join(picked).strip()
    if len(summary) > MAX_SUMMARY_CHARS:
        summary = summary[: MAX_SUMMARY_CHARS - 1].rstrip() + "…"
    if req and summary and req not in summary:
        summary = f"【按要求「{req[:40]}」整理】{summary}"
    if not summary:
        summary = "（草稿）正文较短，请直接编辑摘要。"

    pool = " ".join([title, summary, req, text[:2000]])
    counts: dict[str, int] = {}
    for tok in _tokenize(pool):
        counts[tok] = counts.get(tok, 0) + 1
    ranked = sorted(
        counts.items(),
        key=lambda kv: (kv[0] in _tokenize(req), len(kv[0]) >= 2, kv[1], len(kv[0])),
        reverse=True,
    )
    keywords = [k for k, _ in ranked[:MAX_KEYWORDS]]
    if not keywords and title:
        keywords = _tokenize(title)[:6]

    return {
        "title": title,
        "summary": summary,
        "keywords": keywords,
        "draft": True,
    }


draft_bookmark_fields = draft_document_fields


_URL_IN_TEXT_RE = re.compile(
    r"(?:https?|file|ftp|data|javascript|vbscript):[^\s<>\"'`]+",
    re.IGNORECASE,
)
_REQ_HINT_RE = re.compile(
    r"(重点|摘要|复习|做成|关键词|短一点|缩短|再短|加上|请|帮我|要求|整理|摘取|摘)"
)
_SHORTEN_RE = re.compile(r"(短一点|缩短|再短|更短)")
_ADD_KEYWORD_RE = re.compile(
    r"关键词[^。\n]{0,12}加上\s*[「『\"]?([^」』\"。\n；;]+)[」』\"]?"
)


def _looks_like_requirement(text: str) -> bool:
    s = (text or "").strip()
    if not s or len(s) > 60:
        return False
    if _REQ_HINT_RE.search(s):
        return True
    return len(s) <= 40


def _looks_like_article_text(text: str) -> bool:
    s = (text or "").strip()
    if len(s) >= 50:
        return True
    if s.count("\n") >= 1 and len(s) >= 30:
        return True
    return False


def extract_ingest_fields(message: str) -> dict[str, Any]:
    """Split a message into url / text / requirement without rejecting empties."""
    raw = (message or "").strip()
    urls = _URL_IN_TEXT_RE.findall(raw)
    cleaned_urls: list[str] = []
    for u in urls:
        cleaned_urls.append(u.rstrip(".,;:)]}>\"'"))
    urls = cleaned_urls

    remainder = raw
    for u in urls:
        remainder = remainder.replace(u, " ", 1)
    remainder = re.sub(r"[ \t]+\n", "\n", remainder)
    remainder = re.sub(r"\n{3,}", "\n\n", remainder)
    remainder = re.sub(r"[ \t]{2,}", " ", remainder).strip()

    url = urls[0] if urls else ""
    extra_urls = urls[1:]
    text = ""
    requirement = ""

    if remainder:
        lines = [ln.strip() for ln in remainder.splitlines() if ln.strip()]
        if _looks_like_article_text(remainder):
            if len(lines) >= 2 and _looks_like_requirement(lines[-1]):
                text = "\n".join(lines[:-1]).strip()
                requirement = lines[-1]
            else:
                text = remainder
        elif _looks_like_requirement(remainder) or (
            url and not _looks_like_article_text(remainder)
        ):
            requirement = remainder
        else:
            text = remainder

    if extra_urls:
        note = "其他链接：" + " ".join(extra_urls)
        if text:
            text = f"{text}\n\n{note}"
        elif requirement:
            requirement = f"{requirement}；{note}"
        else:
            requirement = note

    return {
        "ok": True,
        "url": url,
        "text": text,
        "requirement": requirement,
        "extra_urls": extra_urls,
        "message": "ok",
    }


def parse_ingest_message(message: str) -> dict[str, Any]:
    """Split one message for direct ingest; reject when neither url nor text."""
    raw = (message or "").strip()
    if not raw:
        return {
            "ok": False,
            "error": "empty_message",
            "message": "请输入链接、正文或调整要求",
        }
    fields = extract_ingest_fields(raw)
    if not fields.get("url") and not fields.get("text"):
        return {
            "ok": False,
            "error": "need_content",
            "message": "还需要链接或正文才能入库；仅提要求不够",
            "url": "",
            "text": "",
            "requirement": fields.get("requirement") or "",
            "extra_urls": fields.get("extra_urls") or [],
        }
    return fields


def message_suggests_new_ingest(message: str) -> bool:
    """True when the turn looks like content to ingest (not a revise ask)."""
    parsed = parse_ingest_message(message)
    if not parsed.get("ok"):
        return bool(_URL_IN_TEXT_RE.search(message or ""))
    return bool(parsed.get("url") or _looks_like_article_text(str(parsed.get("text") or "")))


def revise_document(
    actor_id: str,
    document_id: str,
    *,
    requirement: str = "",
    generator: Optional[DocumentGenerator] = None,
) -> dict[str, Any]:
    """Re-draft title/summary (and internal keywords) from document body."""
    safe = normalize_actor_id(actor_id)
    req = (requirement or "").strip()
    if not req:
        return {
            "ok": False,
            "error": "invalid_request",
            "message": "请提供调整要求",
        }
    did = (document_id or "").strip()
    if not did:
        return {
            "ok": False,
            "error": "invalid_request",
            "message": "document id required",
        }

    with _lock_for(safe):
        items = _load_documents(safe)
        target = None
        for item in items:
            if str(item.get("id")) == did:
                target = item
                break
        if target is None:
            return {"ok": False, "error": "not_found", "message": "文档不存在"}

        body = str(target.get("body") or "").strip()
        title = str(target.get("title") or "")
        summary = str(target.get("summary") or "")
        keywords = list(target.get("keywords") or [])

        add_match = _ADD_KEYWORD_RE.search(req)
        if add_match:
            added = _normalize_keywords(
                re.split(r"[,，、/\s]+", add_match.group(1).strip())
            )
            keywords = _merge_keywords(keywords, added)
        elif _SHORTEN_RE.search(req) and summary:
            keep = max(80, len(summary) // 2)
            if len(summary) > keep:
                summary = summary[: keep - 1].rstrip() + "…"
            if req and "【按要求" not in summary[:20]:
                summary = f"【按要求「{req[:40]}」整理】{summary}"
        else:
            if not body:
                return {
                    "ok": False,
                    "error": "empty_body",
                    "message": "该文档没有可重写的正文",
                }
            gen = generator or draft_document_fields
            try:
                fields = gen(body, title_hint=title, requirement=req)
            except TypeError:
                fields = gen(body)
            except Exception:  # noqa: BLE001
                fields = draft_document_fields(
                    body, title_hint=title, requirement=req
                )
            title = str(fields.get("title") or title)[:120]
            summary = str(fields.get("summary") or summary)
            keywords = _normalize_keywords(fields.get("keywords") or keywords)

        target["title"] = title[:120] or target.get("title") or "未命名文档"
        target["summary"] = summary[: MAX_SUMMARY_CHARS * 2]
        target["keywords"] = keywords
        target["requirement"] = req
        target["updated_at"] = _now()
        target["draft"] = True
        _save_documents(safe, items)
        pub = _public_document(target)
        return {
            "ok": True,
            "actor_id": safe,
            "document": pub,
            "bookmark": pub,
            "revised": True,
            "message": "已按要求更新文档",
        }


revise_bookmark = revise_document


def keyword_jaccard(a: list[str], b: list[str]) -> float:
    sa = {x.lower() for x in a if x}
    sb = {x.lower() for x in b if x}
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


def keyword_intersection_size(a: list[str], b: list[str]) -> int:
    sa = {x.lower() for x in a if x}
    sb = {x.lower() for x in b if x}
    return len(sa & sb)


def should_merge_by_keywords(a: list[str], b: list[str]) -> bool:
    """Clear rule: Jaccard ≥ 0.5 and shared keywords ≥ 2 → merge candidates."""
    return (
        keyword_jaccard(a, b) >= KEYWORD_MERGE_JACCARD
        and keyword_intersection_size(a, b) >= KEYWORD_MERGE_MIN_INTERSECTION
    )


def _find_by_url(documents: list[dict[str, Any]], url: str) -> dict[str, Any] | None:
    target = (url or "").strip()
    if not target:
        return None
    for item in documents:
        if str(item.get("url") or "").strip() == target:
            return item
    return None


def _find_keyword_overlap(
    documents: list[dict[str, Any]], keywords: list[str]
) -> dict[str, Any] | None:
    best = None
    best_score = 0.0
    for item in documents:
        existing = list(item.get("keywords") or [])
        if not should_merge_by_keywords(existing, keywords):
            continue
        score = keyword_jaccard(existing, keywords)
        if score > best_score:
            best_score = score
            best = item
    return best


def _merge_keywords(*groups: list[str]) -> list[str]:
    out: list[str] = []
    for group in groups:
        for k in group:
            k = str(k).strip()
            if k and k not in out:
                out.append(k)
            if len(out) >= MAX_KEYWORDS:
                return out
    return out


def save_document(
    actor_id: str,
    document_id: str,
    *,
    title: str | None = None,
    summary: str | None = None,
    body: str | None = None,
    keywords: Any = None,
) -> dict[str, Any]:
    """Update editable fields on an existing document."""
    safe = normalize_actor_id(actor_id)
    with _lock_for(safe):
        items = _load_documents(safe)
        target = None
        for item in items:
            if str(item.get("id")) == str(document_id):
                target = item
                break
        if target is None:
            return {"ok": False, "error": "not_found", "message": "文档不存在"}
        if title is not None:
            target["title"] = str(title).strip()[:120] or target.get("title") or "未命名文档"
        if summary is not None:
            target["summary"] = str(summary).strip()[: MAX_SUMMARY_CHARS * 2]
        if body is not None:
            body_s = str(body)
            if len(body_s) > MAX_TEXT_CHARS:
                body_s = body_s[:MAX_TEXT_CHARS]
            target["body"] = body_s
            target["char_count"] = len(body_s)
        if keywords is not None:
            target["keywords"] = _normalize_keywords(keywords)
        target["updated_at"] = _now()
        target["draft"] = False
        _save_documents(safe, items)
        pub = _public_document(target)
        return {"ok": True, "actor_id": safe, "document": pub, "bookmark": pub}


save_bookmark = save_document


def ingest_document(
    actor_id: str,
    *,
    text: str = "",
    url: str = "",
    requirement: str = "",
    title_hint: str = "",
    filename: str = "",
    content_base64: str = "",
    content_type: str = "",
    kind: str = "",
    fetcher: Optional[Fetcher] = None,
    generator: Optional[DocumentGenerator] = None,
    resolve: bool = True,
) -> dict[str, Any]:
    """Create or merge one document from URL, paste, PDF, or local file."""
    safe = normalize_actor_id(actor_id)
    url = (url or "").strip()
    text = (text or "").strip()
    requirement = (requirement or "").strip()
    title_hint = (title_hint or "").strip()
    filename = (filename or "").strip()
    kind_hint = (kind or "").strip().lower()

    if content_base64 or (filename and not text and not url):
        decoded = decode_upload_payload(
            filename=filename,
            content_base64=content_base64,
            text=text,
            content_type=content_type,
        )
        if not decoded.get("ok"):
            return decoded
        text = str(decoded.get("text") or "")
        filename = str(decoded.get("filename") or filename)
        kind_hint = str(decoded.get("kind") or kind_hint)

    if not url and not text:
        return {"ok": False, "error": "empty_input", "message": "请提供链接、正文或本地文件"}

    page_title = ""
    if url:
        ok, reason = validate_ingest_url(url, resolve=resolve)
        if not ok:
            return {"ok": False, "error": "invalid_url", "message": reason}
        if not text:
            fetch = fetcher or _default_fetcher
            try:
                fetched_ok, err_or_url, body = fetch(url)
            except Exception as exc:  # noqa: BLE001
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
            # PDF URL body
            if body[:5] == b"%PDF-" or url.lower().endswith(".pdf"):
                text = extract_pdf_text(body)
                kind_hint = kind_hint or "pdf"
                if not text.strip():
                    return {
                        "ok": False,
                        "error": "empty_body",
                        "message": "无法从 PDF 提取正文",
                    }
            else:
                raw = body.decode("utf-8", errors="replace")
                page_title, text = _strip_html(raw)
                if not text.strip():
                    return {
                        "ok": False,
                        "error": "empty_body",
                        "message": "页面无可提取正文",
                    }

    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS]

    gen = generator or draft_document_fields
    try:
        fields = gen(text, title_hint=title_hint or page_title or filename, requirement=requirement)
    except TypeError:
        fields = gen(text)
    except Exception:  # noqa: BLE001 — never drop content if generator fails
        fields = draft_document_fields(
            text,
            title_hint=title_hint or page_title or filename,
            requirement=requirement,
        )

    title = str(
        fields.get("title") or title_hint or page_title or filename or "未命名文档"
    )[:120]
    summary = str(fields.get("summary") or "")[: MAX_SUMMARY_CHARS * 2]
    keywords = _normalize_keywords(fields.get("keywords"))
    if not summary:
        fallback = draft_document_fields(
            text, title_hint=title, requirement=requirement
        )
        summary = fallback["summary"]
        keywords = keywords or fallback["keywords"]
        title = title or fallback["title"]

    if kind_hint:
        kind = kind_hint
    elif url:
        kind = "pdf" if url.lower().endswith(".pdf") else "url"
    elif filename.lower().endswith(".pdf"):
        kind = "pdf"
    elif filename:
        kind = "file"
    else:
        kind = "text"

    now = _now()
    merged = False
    merge_reason = ""

    with _lock_for(safe):
        items = _load_documents(safe)
        existing = _find_by_url(items, url) if url else None
        if existing is None and not url:
            existing = _find_keyword_overlap(items, keywords)

        if existing is not None:
            merged = True
            merge_reason = (
                "same_url"
                if url and str(existing.get("url") or "") == url
                else "keyword_overlap"
            )
            existing["title"] = title
            existing["summary"] = summary
            existing["keywords"] = _merge_keywords(
                list(existing.get("keywords") or []), keywords
            )
            existing["body"] = text
            if url:
                existing["url"] = url
            if filename:
                existing["filename"] = filename
            if requirement:
                existing["requirement"] = requirement
            existing["kind"] = kind
            existing["draft"] = bool(fields.get("draft", True))
            existing["updated_at"] = now
            existing["char_count"] = len(text)
            existing["merged_from"] = merge_reason
            record = existing
        else:
            record = {
                "id": _new_id(),
                "title": title,
                "summary": summary,
                "keywords": keywords,
                "url": url,
                "filename": filename,
                "body": text,
                "requirement": requirement,
                "kind": kind,
                "draft": bool(fields.get("draft", True)),
                "ingested_at": now,
                "updated_at": now,
                "char_count": len(text),
                "merged_from": "",
            }
            items.append(record)

        _save_documents(safe, items)

    pub = _public_document(record)
    msg = "已合并到已有文档" if merged else "已加入文档"
    return {
        "ok": True,
        "actor_id": safe,
        "merged": merged,
        "merge_reason": merge_reason,
        "document": pub,
        "bookmark": pub,
        "source": pub,
        "message": msg,
    }


ingest_bookmark = ingest_document


def save_generated_document(
    actor_id: str,
    *,
    title: str,
    body: str,
    summary: str = "",
    source_url: str = "",
    requirement: str = "",
) -> dict[str, Any]:
    """Persist an Agent-generated draft into the personal library (not a local path)."""
    title_s = (title or "").strip() or "Agent 生成文档"
    body_s = (body or "").strip()
    if not body_s:
        return {"ok": False, "error": "empty_body", "message": "生成文稿正文为空，无法保存"}
    return ingest_document(
        actor_id,
        text=body_s,
        url=(source_url or "").strip(),
        requirement=requirement,
        title_hint=title_s,
        kind="agent",
        resolve=False,
        generator=lambda text, **kw: {
            "title": title_s[:120],
            "summary": (summary or "").strip()
            or draft_document_fields(text, title_hint=title_s, requirement=requirement)[
                "summary"
            ],
            "keywords": draft_document_fields(
                text, title_hint=title_s, requirement=requirement
            )["keywords"],
            "draft": False,
        },
    )


def ingest_text(
    actor_id: str,
    text: str,
    *,
    title: str = "",
    source_url: str = "",
    source_id: str | None = None,
    requirement: str = "",
    generator: Optional[DocumentGenerator] = None,
) -> dict[str, Any]:
    """Back-compat wrapper: paste text into a document."""
    return ingest_document(
        actor_id,
        text=text,
        url=source_url or (source_id if (source_id or "").startswith("http") else ""),
        requirement=requirement,
        title_hint=title,
        generator=generator,
        resolve=False,
    )


def ingest_url(
    actor_id: str,
    url: str,
    *,
    fetcher: Optional[Fetcher] = None,
    resolve: bool = True,
    requirement: str = "",
    text: str = "",
    generator: Optional[DocumentGenerator] = None,
) -> dict[str, Any]:
    """Back-compat wrapper: URL (+ optional body override) into a document."""
    return ingest_document(
        actor_id,
        url=url,
        text=text,
        requirement=requirement,
        fetcher=fetcher,
        generator=generator,
        resolve=resolve,
    )


def _score_document(query: str, item: dict[str, Any]) -> float:
    q = (query or "").strip()
    if not q:
        return 0.0
    ql = q.lower()
    tokens = _tokenize(q)
    score = 0.0
    url = str(item.get("url") or "")
    filename = str(item.get("filename") or "")
    title = str(item.get("title") or "")
    summary = str(item.get("summary") or "")
    keywords = [str(k) for k in (item.get("keywords") or [])]
    if url and (url in q or q in url or url.lower() in ql):
        score += 8.0
    if filename and (filename.lower() in ql or any(t in filename.lower() for t in tokens)):
        score += 3.0
    for kw in keywords:
        kl = kw.lower()
        if kl and (kl in ql or any(t == kl or t in kl or kl in t for t in tokens)):
            score += 3.0
        if kw in q:
            score += 1.5
    for tok in tokens:
        if tok in title.lower() or tok in title:
            score += 2.0
        if tok in summary.lower() or tok in summary:
            score += 1.5
    body = str(item.get("body") or "")
    if body:
        for tok in tokens[:20]:
            if tok in body.lower() or tok in body:
                score += 0.25
    return score


_score_bookmark = _score_document


def search_personal(
    actor_id: str,
    query: str,
    *,
    top_k: int = 3,
) -> dict[str, Any]:
    """Search documents by body, summary, title, URL, filename, and keywords."""
    safe = normalize_actor_id(actor_id)
    items = _load_documents(safe)
    process: list[dict[str, str]] = [
        {
            "step": "personal_kb",
            "detail": f"actor={safe} documents={len(items)}",
        }
    ]
    if not items:
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
            "hint": "个人库中没有足够依据。请先加入链接、PDF、本地文档或粘贴正文后再提问。",
        }

    scored: list[tuple[float, dict[str, Any]]] = []
    for item in items:
        sc = _score_document(query, item)
        if sc > 0:
            scored.append((sc, item))
    scored.sort(key=lambda x: x[0], reverse=True)
    process.append(
        {
            "step": "document_search",
            "detail": (
                f"title/summary/body/url/filename hits={len(scored)} "
                f"(top_k={top_k})"
            ),
        }
    )
    # Keep legacy step name so older offline assertions still see personal search.
    process.append(
        {
            "step": "bookmark_search",
            "detail": f"alias_of=document_search hits={len(scored)}",
        }
    )

    results: list[dict[str, Any]] = []
    for sc, item in scored[: max(top_k, 1)]:
        url = str(item.get("url") or "")
        filename = str(item.get("filename") or "")
        title = str(item.get("title") or "")
        summary = str(item.get("summary") or "")
        keywords = list(item.get("keywords") or [])
        body = str(item.get("body") or "")
        content = summary
        if body and body not in content:
            content = f"{summary}\n\n{body[:600]}" if summary else body[:800]
        cite_source = url or filename or f"document_{item.get('id') or 'x'}.md"
        results.append(
            {
                "source": cite_source,
                "title": title,
                "url": url,
                "filename": filename,
                "score": sc,
                "content": content[:1200],
                "keywords": keywords,
                "document_id": item.get("id"),
                "bookmark_id": item.get("id"),
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
            "hint": "个人库中没有足够依据。可换个问法，或先加入相关资料。",
        }

    return {
        "ok": True,
        "results": results,
        "docs_sources": ["personal"],
        "retrieval_process": process,
    }


def _content_fingerprint(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]
