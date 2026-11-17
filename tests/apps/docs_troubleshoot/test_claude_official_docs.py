"""Fixture-based tests for Claude official docs retrieval (no live network)."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

os.environ["REACT_AGENT_APP"] = "docs_troubleshoot"
os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")

FIXTURE_DIR = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "docs_troubleshoot"
    / "claude_official"
)

URL_MESSAGES = "https://platform.claude.com/docs/en/api/messages.md"
URL_RATE = "https://platform.claude.com/docs/en/api/rate-limits.md"
URL_AUTH = "https://platform.claude.com/docs/en/manage-claude/authentication.md"
URL_INDEX = "https://platform.claude.com/llms.txt"

PAGE_MAP = {
    URL_INDEX: "llms.txt",
    URL_MESSAGES: "messages.md",
    URL_RATE: "rate-limits.md",
    URL_AUTH: "authentication.md",
}


@pytest.fixture(autouse=True)
def _reset_env(tmp_path, monkeypatch):
    from react_agent.apps.docs_troubleshoot.docs_sources import set_docs_sources
    from react_agent.apps.docs_troubleshoot.index import reset_index

    for key in (
        "REACT_AGENT_DOCS_SOURCES",
        "REACT_AGENT_DOCS_GIT_ROOT",
        "REACT_AGENT_DOCS_GIT_PREFIX",
        "REACT_AGENT_DOCS_INGEST_DIRS",
        "REACT_AGENT_CLAUDE_DOCS_CACHE_DIR",
        "REACT_AGENT_CLAUDE_DOCS_CACHE_TTL",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("REACT_AGENT_CLAUDE_DOCS_CACHE_DIR", str(tmp_path / "claude-cache"))
    monkeypatch.setenv("REACT_AGENT_CLAUDE_DOCS_CACHE_TTL", "600")
    set_docs_sources(None)
    reset_index()
    yield
    set_docs_sources(None)
    reset_index()


def _fixture_fetcher(url: str) -> tuple[bool, str, str]:
    name = PAGE_MAP.get(url)
    if not name:
        return False, f"unexpected url: {url}", ""
    path = FIXTURE_DIR / name
    return True, url, path.read_text(encoding="utf-8")


def test_select_index_entries_by_title_summary():
    from react_agent.apps.docs_troubleshoot.claude_docs import (
        parse_llms_index,
        select_index_entries,
    )

    entries = parse_llms_index((FIXTURE_DIR / "llms.txt").read_text(encoding="utf-8"))
    assert len(entries) >= 4
    ranked = select_index_entries(entries, "Messages API max_tokens", top_k=2)
    assert ranked
    assert ranked[0][1].url == URL_MESSAGES


def test_search_returns_official_urls(monkeypatch):
    from react_agent.apps.docs_troubleshoot import claude_docs
    from react_agent.apps.docs_troubleshoot.claude_docs import search_claude_official

    monkeypatch.setattr(claude_docs, "_default_fetcher", _fixture_fetcher)
    out = search_claude_official("Messages API request body", top_k=2, fetcher=_fixture_fetcher)
    assert out["ok"] is True
    assert out["results"]
    assert all(r["source"].startswith("https://platform.claude.com/") for r in out["results"])
    assert all(r.get("url", "").startswith("https://platform.claude.com/") for r in out["results"])
    assert any("Messages" in (r.get("title") or "") for r in out["results"])
    assert out["retrieval_process"]


def test_citations_include_official_link(monkeypatch):
    from react_agent.apps.docs_troubleshoot.docs_sources import set_docs_sources
    from react_agent.apps.docs_troubleshoot.policy import enforce_answer_policy
    from react_agent.apps.docs_troubleshoot.synthesize import synthesize_draft
    from react_agent.apps.docs_troubleshoot import claude_docs

    monkeypatch.setattr(claude_docs, "_default_fetcher", _fixture_fetcher)
    set_docs_sources(["claude_official"])
    out = claude_docs.search_claude_official(
        "rate limits 429 retry-after", top_k=1, fetcher=_fixture_fetcher
    )
    assert out["ok"]
    draft, sources = synthesize_draft("rate limits 429", out["results"])
    assert sources
    assert sources[0].startswith("https://platform.claude.com/")
    assert "来源:" in draft
    assert "https://platform.claude.com/" in draft
    policy = enforce_answer_policy(draft, allowed_sources=sources)
    assert policy["refused"] is False
    assert policy["citations"]
    assert policy["citations"][0]["url"].startswith("https://platform.claude.com/")


def test_insufficient_evidence_refuses(monkeypatch):
    from react_agent.apps.docs_troubleshoot import claude_docs
    from react_agent.apps.docs_troubleshoot.docs_sources import set_docs_sources
    from react_agent.apps.docs_troubleshoot.offline_answer import answer_offline

    monkeypatch.setattr(claude_docs, "_default_fetcher", _fixture_fetcher)
    set_docs_sources(["claude_official"])
    out = answer_offline(
        "完全无关的冷门主题 xyzzy-plugh-no-match-ever",
        docs_sources="claude_official",
    )
    assert out["refused"] is True
    assert out["citations"] == []


def test_official_only_does_not_silently_use_corpus(monkeypatch):
    from react_agent.apps.docs_troubleshoot import claude_docs
    from react_agent.apps.docs_troubleshoot.docs_sources import set_docs_sources
    from react_agent.apps.docs_troubleshoot.tools import search_docs

    def boom(_url: str) -> tuple[bool, str, str]:
        return False, "network down", ""

    monkeypatch.setattr(claude_docs, "_default_fetcher", boom)
    set_docs_sources(["claude_official"])
    data = json.loads(search_docs("Authorization Bearer 401", top_k=3))
    assert data["ok"] is False
    assert "claude_official" in data.get("message", "")
    assert data["results"] == []
    # Must not return builtin corpus hits while claiming official-only.
    blob = json.dumps(data, ensure_ascii=False)
    assert "api_auth.md" not in blob
    assert "未改用内置演示语料" in (data.get("hint") or "")


def test_cache_stays_outside_repo(monkeypatch):
    import tempfile

    from react_agent.apps.docs_troubleshoot import claude_docs

    cache_dir = Path(tempfile.gettempdir()) / "react-agent-claude-docs-test-cache"
    if cache_dir.exists():
        for p in cache_dir.glob("*"):
            p.unlink()
    monkeypatch.setenv("REACT_AGENT_CLAUDE_DOCS_CACHE_DIR", str(cache_dir))
    monkeypatch.setattr(claude_docs, "_default_fetcher", _fixture_fetcher)
    out = claude_docs.search_claude_official(
        "authentication api key", top_k=1, fetcher=_fixture_fetcher
    )
    assert out["ok"]
    assert cache_dir.exists()
    cached = list(cache_dir.glob("*.json"))
    assert cached
    payload = json.loads(cached[0].read_text(encoding="utf-8"))
    assert payload["url"].startswith("https://platform.claude.com/")
    assert "fetched_at" in payload
    assert "source" in payload
    # Default/runtime cache must not land in package corpus/ or be a tracked path.
    repo_root = Path(__file__).resolve().parents[3]
    corpus = repo_root / "src" / "react_agent" / "apps" / "docs_troubleshoot" / "corpus"
    assert corpus not in cache_dir.resolve().parents
    assert "corpus" not in cache_dir.parts
    gitignore = (repo_root / ".gitignore").read_text(encoding="utf-8")
    assert "claude-docs-cache" in gitignore
    # Explicit override under system temp is outside the git worktree.
    assert repo_root not in cache_dir.resolve().parents


def test_default_source_remains_corpus_for_search(monkeypatch):
    from react_agent.apps.docs_troubleshoot.docs_sources import set_docs_sources
    from react_agent.apps.docs_troubleshoot.tools import search_docs

    set_docs_sources(["corpus"])
    data = json.loads(search_docs("Authorization Bearer 401", top_k=3))
    assert data["ok"]
    assert data.get("docs_sources") == ["corpus"]
    assert any("api" in (r.get("source") or "").lower() for r in data["results"])
