"""Personal knowledge base: ingest, actor isolation, refuse, illegal URL (offline)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE_HTML = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "docs_troubleshoot"
    / "personal_kb"
    / "sample_note.html"
)


@pytest.fixture()
def personal_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("REACT_AGENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REACT_AGENT_RAG_MODE", "keyword")
    monkeypatch.setenv("REACT_AGENT_DISABLE_MCP", "1")
    from react_agent.apps.docs_troubleshoot.personal_kb import clear_actor_cache

    clear_actor_cache()
    yield tmp_path
    clear_actor_cache()


def _fixture_fetcher(url: str):
    raw = FIXTURE_HTML.read_bytes()
    return True, url, raw


def test_ingest_text_lists_source_and_survives_reload(personal_tmp):
    from react_agent.apps.docs_troubleshoot.personal_kb import (
        clear_actor_cache,
        get_actor_rag,
        ingest_text,
        list_sources,
    )

    out = ingest_text(
        "employee-a",
        "个人备忘：429 时按 Retry-After 退避。单用户每分钟不超过 60 次。",
        title="限流备忘",
    )
    assert out["ok"] is True
    assert out["chunk_count"] >= 1
    sources = list_sources("employee-a")
    assert len(sources) == 1
    assert sources[0]["title"] == "限流备忘"
    assert sources[0]["chunk_count"] >= 1

    clear_actor_cache("employee-a")
    rag = get_actor_rag("employee-a")
    assert len(rag.chunks) >= 1
    assert list_sources("employee-a")[0]["title"] == "限流备忘"


def test_ingest_url_uses_fixture_not_network(personal_tmp):
    from react_agent.apps.docs_troubleshoot.personal_kb import ingest_url, list_sources

    url = "https://example.com/personal-note"
    out = ingest_url("employee-a", url, fetcher=_fixture_fetcher, resolve=False)
    assert out["ok"] is True
    assert out["chunk_count"] >= 1
    src = list_sources("employee-a")[0]
    assert src["url"] == url
    assert "限流" in src["title"] or "笔记" in src["title"]


def test_actor_isolation(personal_tmp):
    from react_agent.apps.docs_troubleshoot.personal_kb import (
        ingest_text,
        list_sources,
        search_personal,
    )

    ingest_text("alice", "Alice 私有笔记：密钥轮换周期是 90 天。", title="alice-note")
    ingest_text("bob", "Bob 私有笔记：差旅餐补上限 80 元。", title="bob-note")

    assert list_sources("alice")[0]["title"] == "alice-note"
    assert list_sources("bob")[0]["title"] == "bob-note"

    alice_hits = search_personal("alice", "密钥轮换")
    bob_hits = search_personal("bob", "密钥轮换")
    assert alice_hits["ok"] is True
    assert any("90" in (r.get("content") or "") for r in alice_hits["results"])
    assert bob_hits.get("ok") is False or not any(
        "90" in (r.get("content") or "") for r in bob_hits.get("results") or []
    )


def test_illegal_urls_rejected(personal_tmp):
    from react_agent.apps.docs_troubleshoot.personal_kb import ingest_url, list_sources

    for bad in (
        "file:///etc/passwd",
        "http://localhost/secret",
        "http://127.0.0.1/x",
        "http://192.168.1.10/internal",
    ):
        out = ingest_url("employee-a", bad, resolve=False)
        assert out["ok"] is False
        assert out.get("error") == "invalid_url"
    assert list_sources("employee-a") == []


def test_empty_personal_kb_refuses_without_corpus(personal_tmp):
    from react_agent.apps.docs_troubleshoot.offline_answer import answer_offline
    from react_agent.tools import enable_app_tools

    enable_app_tools()
    out = answer_offline(
        "缺少 Authorization 返回什么？",
        docs_sources="personal",
        actor_id="empty-user",
    )
    assert out["refused"] is True
    assert "个人库中没有足够依据" in out["answer"]
    # Must not answer from the 14 builtin corpus articles.
    assert "401" not in out["answer"] or "个人库" in out["answer"]
    process = json.dumps(out.get("retrieval_process") or [], ensure_ascii=False)
    assert "personal" in process.lower() or "个人" in process
    assert "builtin corpus" not in process.lower()


def test_ask_after_ingest_returns_citations(personal_tmp):
    from react_agent.apps.docs_troubleshoot.offline_answer import answer_offline
    from react_agent.apps.docs_troubleshoot.personal_kb import ingest_text
    from react_agent.tools import enable_app_tools

    enable_app_tools()
    ingest_text(
        "employee-c",
        "当上游返回 429 时，客户端应指数退避重试，并优先尊重 Retry-After 响应头。"
        "单用户突发流量不超过每分钟 60 次。",
        title="限流笔记",
        source_url="https://example.com/rate-limit-note",
    )
    out = answer_offline(
        "429 时应该怎么处理？",
        docs_sources="personal",
        actor_id="employee-c",
    )
    assert out["refused"] is False
    assert "429" in out["answer"] or "重试" in out["answer"] or "Retry-After" in out["answer"]
    cites = out.get("citations") or []
    assert cites
    joined = " ".join(
        str(c.get("url") or c.get("source") or "") for c in cites if isinstance(c, dict)
    )
    assert "https://example.com/rate-limit-note" in joined
    assert out.get("docs_sources") == ["personal"]


def test_http_ingest_and_sources_endpoints(personal_tmp):
    from http.server import ThreadingHTTPServer
    import threading
    import time
    import urllib.error
    import urllib.request

    from react_agent.server.app import AgentHandler
    from react_agent.tools import enable_app_tools

    enable_app_tools()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), AgentHandler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.1)
    try:
        bad = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/docs/personal/ingest",
            data=json.dumps({"url": "file:///tmp/x"}).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Actor-Id": "http-user"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(bad, timeout=5)
        assert err.value.code == 400

        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/docs/personal/ingest",
            data=json.dumps(
                {
                    "text": "HTTP 投递：幂等键 Idempotency-Key 用于避免重复扣款。",
                    "title": "幂等备忘",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Actor-Id": "http-user"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        assert body.get("ok") is True
        assert body.get("chunk_count", 0) >= 1

        list_req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/docs/personal/sources",
            headers={"X-Actor-Id": "http-user"},
            method="GET",
        )
        with urllib.request.urlopen(list_req, timeout=5) as resp:
            listed = json.loads(resp.read().decode("utf-8"))
        assert listed.get("source_count") == 1
        assert listed["sources"][0]["title"] == "幂等备忘"

        other = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/docs/personal/sources",
            headers={"X-Actor-Id": "other-user"},
            method="GET",
        )
        with urllib.request.urlopen(other, timeout=5) as resp:
            other_body = json.loads(resp.read().decode("utf-8"))
        assert other_body.get("source_count") == 0
    finally:
        httpd.shutdown()
