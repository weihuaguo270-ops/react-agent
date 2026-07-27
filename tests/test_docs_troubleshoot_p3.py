"""Production blind eval, log/trace evidence, dynamic diagnosis."""
from __future__ import annotations

import json
import os

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
        "REACT_AGENT_TRACE_BACKEND",
    ):
        os.environ.pop(key, None)
    reset_index()
    yield


def test_parse_log_evidence_trace():
    from react_agent.apps.docs_troubleshoot.evidence import parse_log_evidence

    out = parse_log_evidence(
        "trace_id=abc123 level=ERROR error.code=rate_limited HTTP 429",
        trace_id="abc123",
    )
    assert out["type"] == "log_excerpt"
    assert out["trace_id"] == "abc123"
    assert out["highlights"]


def test_parse_trace_context():
    from react_agent.apps.docs_troubleshoot.evidence import parse_trace_context

    out = parse_trace_context(
        json.dumps(
            {
                "trace_id": "tr-1",
                "spans": [{"name": "call", "service": "gw", "error": "timeout"}],
            }
        )
    )
    assert out["type"] == "trace_context"
    assert out["error_span_count"] == 1


def test_cause_infer_aligned():
    from react_agent.apps.docs_troubleshoot.cause_infer import infer_causes_from_retrieval

    hits = [
        {
            "source": "production_corpus/prod_rate_limit_headers.md",
            "content": "429 限流响应头 Retry-After: 60 客户端须退避",
        }
    ]
    bundle = {
        "items": [
            {"type": "http_error", "status_code": 429, "error_code": "rate_limited"}
        ],
        "count": 1,
    }
    causes = infer_causes_from_retrieval(hits, evidence_bundle=bundle, query="429 退避")
    assert causes
    assert any(c.get("aligned_field") for c in causes)


def test_fix_steps_gate_blocks_destructive():
    from react_agent.apps.docs_troubleshoot.fix_policy import gate_fix_steps

    allowed, blocked, pending = gate_fix_steps(
        ["核对 HTTP 状态码", "drop table 清理", "在客户端添加 Authorization Bearer"]
    )
    assert allowed == ["核对 HTTP 状态码"]
    assert blocked
    assert pending


def test_production_eval_suite():
    from react_agent.apps.docs_troubleshoot.eval_production import run_production_eval

    report = run_production_eval()
    assert report["total"] >= 5
    assert report["passed"] == report["total"], [
        (r["id"], r.get("fail_reason")) for r in report["rows"] if not r["passed"]
    ]


def test_fault_eval_with_log_cases():
    from react_agent.apps.docs_troubleshoot.eval_fault import run_fault_eval

    report = run_fault_eval()
    assert report["total"] >= 12
    assert report["passed"] == report["total"], [
        (r["id"], r.get("fail_reason")) for r in report["rows"] if not r["passed"]
    ]
