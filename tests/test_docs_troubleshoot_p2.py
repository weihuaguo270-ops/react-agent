"""Ingest, evidence, and fault-sim eval tests."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

os.environ["REACT_AGENT_APP"] = "docs_troubleshoot"
os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")


@pytest.fixture(autouse=True)
def _reset():
    from react_agent.apps.docs_troubleshoot.index import reset_index

    for key in (
        "REACT_AGENT_DOCS_GIT_ROOT",
        "REACT_AGENT_DOCS_GIT_PREFIX",
        "REACT_AGENT_DOCS_INGEST_DIRS",
    ):
        os.environ.pop(key, None)
    reset_index()
    yield


def test_openapi_ingest_adds_chunks():
    os.environ["REACT_AGENT_INGEST_OPENAPI"] = "1"
    from react_agent.apps.docs_troubleshoot.index import reset_index, get_index

    reset_index()
    rag = get_index()
    sources = " ".join(rag.sources)
    assert "openapi/" in sources or "openapi_sample" in sources


def test_incremental_manifest_stable():
    from react_agent.apps.docs_troubleshoot.index import get_index, reset_index

    reset_index()
    rag1 = get_index()
    n1 = len(rag1.chunks)
    rag2 = get_index()
    assert len(rag2.chunks) == n1


def test_parse_error_evidence():
    from react_agent.apps.docs_troubleshoot.evidence import parse_error_evidence

    out = parse_error_evidence(
        status_code=401,
        body_json='{"error":{"code":"unauthorized","message":"missing bearer token"}}',
    )
    assert out["error_code"] == "unauthorized"
    assert out["status_code"] == 401


def test_workflow_with_error_evidence():
    from react_agent.workflow import run_workflow

    result = run_workflow(
        "docs_troubleshoot",
        {
            "query": "401 missing bearer token 原因？",
            "error_response": {
                "status_code": 401,
                "body": {"error": {"code": "unauthorized", "message": "missing bearer token"}},
            },
        },
    )
    assert result.ok
    assert not result.refused
    assert "401" in result.answer or "Bearer" in result.answer
    causes = result.diagnosis.get("candidate_causes") or []
    assert causes
    assert any("Bearer" in c.get("cause", "") or "401" in c.get("cause", "") for c in causes)


def test_fault_eval_suite():
    from react_agent.apps.docs_troubleshoot.eval_fault import run_fault_eval

    report = run_fault_eval()
    assert report["total"] >= 12
    assert report["passed"] == report["total"], [
        (r["id"], r.get("fail_reason")) for r in report["rows"] if not r["passed"]
    ]
    metrics = report.get("metrics") or {}
    assert metrics.get("root_cause_hit_rate", 0) >= 1.0
    assert metrics.get("wrong_suggestion_rate", 1) == 0.0


def test_cause_rules_401():
    from react_agent.apps.docs_troubleshoot.cause_rules import match_cause_rules

    rules = match_cause_rules(
        query="401 bearer",
        evidence_bundle={
            "items": [
                {"type": "http_error", "status_code": 401, "error_code": "unauthorized"}
            ]
        },
    )
    assert any(r.get("id") == "auth_401" for r in rules)


def test_synthesize_draft_sections():
    from react_agent.apps.docs_troubleshoot.synthesize import synthesize_draft

    hits = [
        {
            "source": "corpus/api_auth.md",
            "content": "401 unauthorized 需在 Authorization 头携带 Bearer API Key。",
        }
    ]
    draft, sources = synthesize_draft("401 unauthorized", hits, field_summary="HTTP 401")
    assert "【现场证据】" in draft
    assert "api_auth.md" in sources[0]
    assert "来源:" in draft
