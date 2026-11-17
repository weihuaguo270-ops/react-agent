"""Resolve active documentation sources for 规范咨询 (docs_troubleshoot).

Sources are additive and request-scoped. Default remains the built-in corpus so
existing golden / git_docs evaluations stay unchanged unless explicitly enabled.
"""
from __future__ import annotations

import os
from contextvars import ContextVar, Token
from typing import Iterable

SOURCE_CORPUS = "corpus"
SOURCE_CLAUDE_OFFICIAL = "claude_official"
KNOWN_SOURCES = frozenset({SOURCE_CORPUS, SOURCE_CLAUDE_OFFICIAL})

_override: ContextVar[tuple[str, ...] | None] = ContextVar(
    "docs_troubleshoot_sources", default=None
)


def parse_docs_sources(raw: str | Iterable[str] | None) -> list[str]:
    """Normalize a sources string/list; unknown tokens are dropped."""
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = [p.strip().lower() for p in raw.replace(";", ",").split(",")]
    else:
        parts = [str(p).strip().lower() for p in raw]
    out: list[str] = []
    for part in parts:
        if not part or part not in KNOWN_SOURCES:
            continue
        if part not in out:
            out.append(part)
    return out


def resolve_docs_sources(
    request_sources: str | Iterable[str] | None = None,
) -> list[str]:
    """Request override → context override → env → default ``corpus``."""
    parsed = parse_docs_sources(request_sources)
    if parsed:
        return parsed
    ctx = _override.get()
    if ctx:
        return list(ctx)
    env = parse_docs_sources(os.environ.get("REACT_AGENT_DOCS_SOURCES", ""))
    return env or [SOURCE_CORPUS]


def set_docs_sources(sources: Iterable[str] | None) -> Token:
    """Bind sources for the current request/tool call stack."""
    parsed = parse_docs_sources(sources) if sources is not None else None
    return _override.set(tuple(parsed) if parsed else None)


def reset_docs_sources(token: Token) -> None:
    """Restore previous request-scoped sources binding."""
    _override.reset(token)


def uses_claude_official(sources: Iterable[str] | None = None) -> bool:
    active = list(sources) if sources is not None else resolve_docs_sources()
    return SOURCE_CLAUDE_OFFICIAL in active


def uses_corpus(sources: Iterable[str] | None = None) -> bool:
    active = list(sources) if sources is not None else resolve_docs_sources()
    return SOURCE_CORPUS in active


def source_display_label(sources: Iterable[str] | None = None) -> str:
    active = list(sources) if sources is not None else resolve_docs_sources()
    labels = []
    for s in active:
        if s == SOURCE_CLAUDE_OFFICIAL:
            labels.append("Claude 官方文档 (platform.claude.com)")
        elif s == SOURCE_CORPUS:
            labels.append("内置演示语料")
        else:
            labels.append(s)
    return " + ".join(labels) if labels else "内置演示语料"
