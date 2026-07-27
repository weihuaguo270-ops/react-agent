"""Docs/API troubleshoot app — offline tests."""
from __future__ import annotations

import json
import os

import pytest

os.environ["REACT_AGENT_APP"] = "docs_troubleshoot"
os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")


@pytest.fixture(autouse=True)
def _reset_index():
    from react_agent.apps.docs_troubleshoot.index import reset_index

    reset_index()
    yield


def test_search_docs_hits_api_auth():
    from react_agent.apps.docs_troubleshoot.tools import search_docs

    data = json.loads(search_docs("Authorization Bearer 401", top_k=3))
    assert data["ok"]
    blob = " ".join(r["content"] for r in data["results"])
    assert "401" in blob or "Authorization" in blob


def test_lookup_api_prefers_api_reference():
    from react_agent.apps.docs_troubleshoot.tools import lookup_api

    data = json.loads(lookup_api("health", top_k=2))
    assert data["ok"]
    sources = [r["source"] for r in data["results"]]
    assert any("api" in s.lower() for s in sources)


def test_verify_citations_rejects_uncited():
    from react_agent.apps.docs_troubleshoot.tools import verify_citations_tool

    check = json.loads(verify_citations_tool("随便猜一个答案，没有任何依据。"))
    assert check["ok"] is False
    assert check["reason"] == "no_citation"


def test_verify_citations_accepts_source():
    from react_agent.apps.docs_troubleshoot.tools import verify_citations_tool

    check = json.loads(
        verify_citations_tool("缺少 Token 返回 401。来源: api_reference.md")
    )
    assert check["ok"] is True


def test_policy_refuse_uncited():
    from react_agent.apps.docs_troubleshoot.policy import enforce_answer_policy

    out = enforce_answer_policy("股价会涨。")
    assert out["refused"] is True


def test_golden_eval_full_pass():
    from react_agent.apps.docs_troubleshoot.eval_golden import run_golden_eval

    report = run_golden_eval()
    assert report["passed"] == report["total"], report["rows"]


def test_app_tools_registered(monkeypatch):
    monkeypatch.setenv("REACT_AGENT_APP", "docs_troubleshoot")
    from react_agent.tools import enable_app_tools, TOOL_REGISTRY

    enable_app_tools()
    assert "search_docs" in TOOL_REGISTRY
    assert "lookup_api" in TOOL_REGISTRY
    assert "verify_citations" in TOOL_REGISTRY
