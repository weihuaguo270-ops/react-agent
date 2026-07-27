"""Git docs held-out, trace MCP backend, fix_steps permission gate."""
from __future__ import annotations

import os

import pytest

os.environ["REACT_AGENT_APP"] = "docs_troubleshoot"
os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")
os.environ.setdefault("REACT_AGENT_PERMISSION_GATE", "1")


@pytest.fixture(autouse=True)
def _reset():
    from react_agent.apps.docs_troubleshoot.index import reset_index

    for key in (
        "REACT_AGENT_DOCS_GIT_ROOT",
        "REACT_AGENT_DOCS_GIT_PREFIX",
        "REACT_AGENT_DOCS_INGEST_DIRS",
        "REACT_AGENT_TRACE_BACKEND",
    ):
        os.environ.pop(key, None)
    reset_index()
    yield


def test_fetch_trace_mock_backend():
    from react_agent.apps.docs_troubleshoot.trace_backend import fetch_trace_bundle

    os.environ["REACT_AGENT_TRACE_BACKEND"] = "mock"
    bundle = fetch_trace_bundle("tr-12")
    assert bundle.get("ok")
    assert bundle.get("trace_id") == "tr-12"
    assert bundle.get("spans")


def test_fetch_trace_mcp_backend():
    from react_agent.apps.docs_troubleshoot.trace_backend import fetch_trace_bundle

    os.environ["REACT_AGENT_TRACE_BACKEND"] = "mcp"
    bundle = fetch_trace_bundle("tr-504")
    assert bundle.get("ok"), bundle
    assert bundle.get("backend") == "mcp"


def test_workflow_enriches_trace_from_backend():
    from react_agent.workflow import run_workflow

    os.environ["REACT_AGENT_TRACE_BACKEND"] = "mock"
    result = run_workflow(
        "docs_troubleshoot",
        {
            "query": "trace tr-504 网关超时原因？",
            "trace_id": "tr-504",
        },
    )
    assert result.ok
    items = (result.diagnosis or {}).get("evidence") or []
    kinds = {e.get("detail", {}).get("type") for e in items if e.get("kind") == "field"}
    assert "trace_context" in kinds


def test_diagnosis_pending_fix_steps_under_gate():
    from react_agent.apps.docs_troubleshoot.diagnosis import build_diagnosis

    os.environ["REACT_AGENT_PERMISSION_GATE"] = "1"
    diag = build_diagnosis(
        query="401 unauthorized",
        evidence_bundle={
            "items": [{"type": "http_error", "status_code": 401, "error_code": "unauthorized"}],
            "count": 1,
        },
        draft="test 来源: api_auth.md",
        ranked_sources=["api_auth.md"],
        refused=False,
        retrieval_hits=[],
    )
    assert diag.get("pending_fix_steps")
    assert not any("drop table" in s for s in diag.get("fix_steps") or [])


def test_git_docs_eval_suite():
    from react_agent.apps.docs_troubleshoot.eval_git_docs import run_git_docs_eval

    report = run_git_docs_eval()
    assert report["total"] >= 5
    assert report["passed"] == report["total"], [
        (r["id"], r.get("fail_reason")) for r in report["rows"] if not r["passed"]
    ]
