"""Personal knowledge base bookmarks: ingest, edit, merge, search, isolation."""
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
    return True, url, FIXTURE_HTML.read_bytes()


def test_parse_ingest_message_splits_url_text_requirement():
    from react_agent.apps.docs_troubleshoot.personal_kb import (
        message_suggests_new_ingest,
        parse_ingest_message,
    )

    url_req = parse_ingest_message(
        "https://example.com/personal-note 重点摘安装步骤"
    )
    assert url_req["ok"] is True
    assert url_req["url"] == "https://example.com/personal-note"
    assert url_req["text"] == ""
    assert "安装" in url_req["requirement"]

    multi = parse_ingest_message(
        "正文第一段讲安装。\n\n第二段讲启动。\nhttps://example.com/a "
        "https://example.com/b 摘要适合复习"
    )
    assert multi["ok"] is True
    assert multi["url"] == "https://example.com/a"
    assert "https://example.com/b" in multi["text"] or "https://example.com/b" in multi[
        "requirement"
    ]
    assert multi["extra_urls"] == ["https://example.com/b"]

    article = parse_ingest_message(
        "安装指南：先安装依赖，再执行 migrate，最后启动服务。\n"
        "复习要点：依赖、migrate、启动。这是足够长的粘贴正文用于识别。"
    )
    assert article["ok"] is True
    assert not article["url"]
    assert "migrate" in article["text"]

    need = parse_ingest_message("摘要再短一点")
    assert need["ok"] is False
    assert need["error"] == "need_content"
    assert message_suggests_new_ingest("https://example.com/x") is True
    assert message_suggests_new_ingest("摘要再短一点") is False


def test_revise_bookmark_updates_same_id(personal_tmp):
    from react_agent.apps.docs_troubleshoot.personal_kb import (
        ingest_bookmark,
        list_bookmarks,
        revise_bookmark,
    )

    first = ingest_bookmark(
        "employee-a",
        text=(
            "安装指南：先安装依赖，再执行 migrate，最后启动服务。"
            "复习要点：依赖、migrate、启动。冷却窗口与 Retry-After。"
        ),
        requirement="重点摘安装步骤",
    )
    assert first["ok"] is True
    bm_id = first["bookmark"]["id"]
    before = first["bookmark"]["summary"]

    shortened = revise_bookmark("employee-a", bm_id, requirement="摘要再短一点")
    assert shortened["ok"] is True
    assert shortened["bookmark"]["id"] == bm_id
    assert len(shortened["bookmark"]["summary"]) <= len(before)

    keyed = revise_bookmark("employee-a", bm_id, requirement="关键词加上安装")
    assert keyed["ok"] is True
    assert "安装" in keyed["bookmark"]["keywords"]
    assert len(list_bookmarks("employee-a")) == 1


def test_ingest_creates_editable_bookmark_draft(personal_tmp):
    from react_agent.apps.docs_troubleshoot.personal_kb import (
        clear_actor_cache,
        ingest_bookmark,
        list_bookmarks,
        save_bookmark,
    )

    out = ingest_bookmark(
        "employee-a",
        text=(
            "安装指南：先安装依赖，再执行 migrate，最后启动服务。"
            "复习要点：依赖、migrate、启动。"
        ),
        requirement="重点摘安装步骤",
    )
    assert out["ok"] is True
    assert out["merged"] is False
    bm = out["bookmark"]
    assert bm["title"]
    assert bm["summary"]
    assert bm["keywords"]
    assert "安装" in bm["summary"] or any("安装" in k for k in bm["keywords"])
    assert bm.get("draft") is True

    listed = list_bookmarks("employee-a")
    assert len(listed) == 1
    saved = save_bookmark(
        "employee-a",
        bm["id"],
        title="我的安装收藏",
        summary="自定义摘要：先装依赖再 migrate。",
        keywords=["安装", "migrate", "启动"],
    )
    assert saved["ok"] is True
    assert saved["bookmark"]["title"] == "我的安装收藏"
    assert saved["bookmark"]["draft"] is False

    clear_actor_cache()
    again = list_bookmarks("employee-a")
    assert again[0]["title"] == "我的安装收藏"
    assert "自定义摘要" in again[0]["summary"]
    assert "migrate" in again[0]["keywords"]


def test_ingest_url_fixture_and_same_url_merges(personal_tmp):
    from react_agent.apps.docs_troubleshoot.personal_kb import (
        ingest_bookmark,
        list_bookmarks,
    )

    url = "https://example.com/personal-note"
    first = ingest_bookmark(
        "employee-a",
        url=url,
        fetcher=_fixture_fetcher,
        resolve=False,
        requirement="摘要适合复习",
    )
    assert first["ok"] is True
    assert first["merged"] is False
    assert first["bookmark"]["url"] == url
    assert first["bookmark"]["keywords"]

    second = ingest_bookmark(
        "employee-a",
        url=url,
        text="更新正文：429 时按 Retry-After 退避，并记录冷却窗口。",
        requirement="摘要适合复习",
        resolve=False,
    )
    assert second["ok"] is True
    assert second["merged"] is True
    assert second["merge_reason"] == "same_url"
    assert len(list_bookmarks("employee-a")) == 1
    assert "429" in list_bookmarks("employee-a")[0]["summary"] or "429" in (
        " ".join(list_bookmarks("employee-a")[0]["keywords"])
    )


def test_keyword_overlap_merges_without_url(personal_tmp):
    from react_agent.apps.docs_troubleshoot.personal_kb import (
        draft_bookmark_fields,
        ingest_bookmark,
        list_bookmarks,
        should_merge_by_keywords,
    )

    assert should_merge_by_keywords(
        ["安装", "migrate", "启动", "依赖"],
        ["安装", "migrate", "启动", "回滚"],
    )
    assert not should_merge_by_keywords(["安装", "依赖"], ["报销", "发票"])

    first = ingest_bookmark(
        "employee-a",
        text="部署手册：安装依赖后执行 migrate，再启动服务。",
        generator=lambda body, **kw: {
            "title": "部署手册",
            "summary": "安装依赖；migrate；启动",
            "keywords": ["安装", "migrate", "启动", "依赖"],
            "draft": True,
        },
    )
    second = ingest_bookmark(
        "employee-a",
        text="补充：安装失败时检查依赖版本，再重跑 migrate 并启动。",
        generator=lambda body, **kw: {
            "title": "部署补充",
            "summary": "安装失败排查",
            "keywords": ["安装", "migrate", "启动", "版本"],
            "draft": True,
        },
    )
    assert second["merged"] is True
    assert second["merge_reason"] == "keyword_overlap"
    assert len(list_bookmarks("employee-a")) == 1
    # Offline draft helper still usable without LLM.
    draft = draft_bookmark_fields("首段内容。第二段。", title_hint="", requirement="")
    assert draft["title"] and draft["summary"] and draft["keywords"] is not None


def test_search_by_keywords_and_url(personal_tmp):
    from react_agent.apps.docs_troubleshoot.personal_kb import (
        ingest_bookmark,
        search_personal,
    )

    ingest_bookmark(
        "employee-c",
        url="https://example.com/rate-limit-note",
        text="当上游返回 429 时，客户端应指数退避重试，并优先尊重 Retry-After。",
        generator=lambda body, **kw: {
            "title": "限流笔记",
            "summary": "429 时指数退避并尊重 Retry-After。",
            "keywords": ["429", "Retry-After", "限流", "退避"],
            "draft": True,
        },
        resolve=False,
    )
    by_kw = search_personal("employee-c", "429 退避")
    assert by_kw["ok"] is True
    assert by_kw["results"][0]["title"] == "限流笔记"
    by_url = search_personal("employee-c", "https://example.com/rate-limit-note")
    assert by_url["ok"] is True
    assert by_url["results"][0]["url"] == "https://example.com/rate-limit-note"


def test_actor_isolation(personal_tmp):
    from react_agent.apps.docs_troubleshoot.personal_kb import (
        ingest_bookmark,
        list_bookmarks,
        search_personal,
    )

    ingest_bookmark(
        "alice",
        text="Alice 私有：密钥轮换周期 90 天。",
        generator=lambda body, **kw: {
            "title": "alice-note",
            "summary": "密钥轮换 90 天",
            "keywords": ["密钥", "轮换", "90"],
            "draft": True,
        },
    )
    ingest_bookmark(
        "bob",
        text="Bob 私有：差旅餐补上限 80 元。",
        generator=lambda body, **kw: {
            "title": "bob-note",
            "summary": "餐补 80",
            "keywords": ["差旅", "餐补", "80"],
            "draft": True,
        },
    )
    assert list_bookmarks("alice")[0]["title"] == "alice-note"
    assert list_bookmarks("bob")[0]["title"] == "bob-note"
    assert search_personal("alice", "密钥轮换")["ok"] is True
    assert search_personal("bob", "密钥轮换").get("ok") is False


def test_illegal_urls_rejected(personal_tmp):
    from react_agent.apps.docs_troubleshoot.personal_kb import (
        ingest_bookmark,
        list_bookmarks,
    )

    for bad in (
        "file:///etc/passwd",
        "http://localhost/secret",
        "http://127.0.0.1/x",
        "http://192.168.1.10/internal",
    ):
        out = ingest_bookmark("employee-a", url=bad, resolve=False)
        assert out["ok"] is False
        assert out.get("error") == "invalid_url"
    assert list_bookmarks("employee-a") == []


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
    assert "401" not in out["answer"] or "个人库" in out["answer"]
    process = json.dumps(out.get("retrieval_process") or [], ensure_ascii=False)
    assert "personal" in process.lower() or "个人" in process
    assert "builtin corpus" not in process.lower()


def test_unrelated_query_with_bookmarks_refuses_without_corpus(personal_tmp):
    """Library has bookmarks, but the question does not match — refuse, no corpus."""
    from react_agent.apps.docs_troubleshoot.offline_answer import answer_offline
    from react_agent.apps.docs_troubleshoot.personal_kb import (
        ingest_bookmark,
        list_bookmarks,
        search_personal,
    )
    from react_agent.tools import enable_app_tools

    enable_app_tools()
    ingest_bookmark(
        "employee-d",
        text="差旅餐补上限 80 元，需保留发票原件。",
        generator=lambda body, **kw: {
            "title": "差旅餐补",
            "summary": "餐补上限 80 元，保留发票。",
            "keywords": ["差旅", "餐补", "发票", "80"],
            "draft": True,
        },
    )
    assert len(list_bookmarks("employee-d")) == 1
    # Corpus-flavored question that the builtin 14 docs would answer with 401.
    miss = search_personal("employee-d", "缺少 Authorization 返回什么？")
    assert miss.get("ok") is False
    assert miss.get("message") == "no_hits"

    out = answer_offline(
        "缺少 Authorization 返回什么？",
        docs_sources="personal",
        actor_id="employee-d",
    )
    assert out["refused"] is True
    assert "个人库中没有足够依据" in out["answer"]
    # Must not silently answer from builtin corpus (api_auth.md → 401).
    assert "401" not in out["answer"]
    assert "unauthorized" not in out["answer"].lower()
    process = json.dumps(out.get("retrieval_process") or [], ensure_ascii=False)
    assert "bookmark_search" in process or "personal" in process.lower()
    assert "builtin corpus" not in process.lower()
    assert out.get("docs_sources") == ["personal"]


def test_ask_after_ingest_returns_citations(personal_tmp):
    from react_agent.apps.docs_troubleshoot.offline_answer import answer_offline
    from react_agent.apps.docs_troubleshoot.personal_kb import ingest_bookmark
    from react_agent.tools import enable_app_tools

    enable_app_tools()
    ingest_bookmark(
        "employee-c",
        url="https://example.com/rate-limit-note",
        text="当上游返回 429 时，客户端应指数退避重试，并优先尊重 Retry-After 响应头。",
        generator=lambda body, **kw: {
            "title": "限流笔记",
            "summary": "429 时指数退避并尊重 Retry-After。",
            "keywords": ["429", "Retry-After", "限流"],
            "draft": True,
        },
        resolve=False,
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


def test_http_bookmark_endpoints(personal_tmp):
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
                    "requirement": "摘要适合复习",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Actor-Id": "http-user"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        assert body.get("ok") is True
        bm = body.get("bookmark") or {}
        assert bm.get("id")
        assert bm.get("summary")
        assert bm.get("keywords") is not None

        chat_req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/docs/personal/ingest",
            data=json.dumps(
                {
                    "message": (
                        "聊天投递正文：限流时按 Retry-After 退避，并记录冷却窗口。"
                        "第二段说明幂等键与重复请求如何处理，便于复习。"
                        "\n摘要适合复习"
                    )
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Actor-Id": "http-user"},
            method="POST",
        )
        with urllib.request.urlopen(chat_req, timeout=5) as resp:
            chat_body = json.loads(resp.read().decode("utf-8"))
        assert chat_body.get("ok") is True
        chat_bm = chat_body.get("bookmark") or {}
        assert chat_bm.get("id")
        assert chat_bm.get("summary")

        need_req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/docs/personal/ingest",
            data=json.dumps({"message": "摘要再短一点"}).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Actor-Id": "http-user"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as need_err:
            urllib.request.urlopen(need_req, timeout=5)
        assert need_err.value.code == 400

        revise_req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/docs/personal/bookmarks/{chat_bm['id']}",
            data=json.dumps({"requirement": "关键词加上限流"}).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Actor-Id": "http-user"},
            method="POST",
        )
        with urllib.request.urlopen(revise_req, timeout=5) as resp:
            revised = json.loads(resp.read().decode("utf-8"))
        assert revised.get("revised") is True
        assert "限流" in (revised.get("bookmark") or {}).get("keywords", [])

        list_req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/docs/personal/bookmarks",
            headers={"X-Actor-Id": "http-user"},
            method="GET",
        )
        with urllib.request.urlopen(list_req, timeout=5) as resp:
            listed = json.loads(resp.read().decode("utf-8"))
        assert listed.get("bookmark_count") == 2

        upd = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/docs/personal/bookmarks/{bm['id']}",
            data=json.dumps(
                {
                    "title": "幂等收藏",
                    "summary": "编辑后的摘要",
                    "keywords": ["幂等", "Idempotency-Key"],
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Actor-Id": "http-user"},
            method="POST",
        )
        with urllib.request.urlopen(upd, timeout=5) as resp:
            saved = json.loads(resp.read().decode("utf-8"))
        assert saved["bookmark"]["title"] == "幂等收藏"

        other = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/docs/personal/bookmarks",
            headers={"X-Actor-Id": "other-user"},
            method="GET",
        )
        with urllib.request.urlopen(other, timeout=5) as resp:
            other_body = json.loads(resp.read().decode("utf-8"))
        assert other_body.get("bookmark_count") == 0
    finally:
        httpd.shutdown()
