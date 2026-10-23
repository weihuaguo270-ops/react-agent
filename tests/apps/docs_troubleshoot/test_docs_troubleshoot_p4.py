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
    import os

    from react_agent.apps.docs_troubleshoot.eval_git_docs import run_git_docs_eval

    env_keys = (
        "REACT_AGENT_DOCS_GIT_ROOT",
        "REACT_AGENT_DOCS_GIT_PREFIX",
        "REACT_AGENT_DOCS_GIT_EXCLUDE",
        "REACT_AGENT_DOCS_INGEST_DIRS",
        "REACT_AGENT_APP",
        "REACT_AGENT_RAG_MODE",
    )
    previous_env = {key: os.environ.get(key) for key in env_keys}
    report = run_git_docs_eval()
    assert {key: os.environ.get(key) for key in env_keys} == previous_env
    assert report["total"] >= 5
    assert report["passed"] == report["total"], [
        (r["id"], r.get("fail_reason")) for r in report["rows"] if not r["passed"]
    ]


def test_git_docs_ingest_excludes_specs_by_default(tmp_path, monkeypatch):
    import subprocess

    from react_agent.apps.docs_troubleshoot.ingest import build_manifest, ingest_git_tracked
    from react_agent.rag import RAG

    repo = tmp_path / "repo"
    (repo / "docs" / "architecture").mkdir(parents=True)
    (repo / "docs" / "specs").mkdir(parents=True)
    (repo / "docs" / "architecture" / "core.md").write_text("Core guide", encoding="utf-8")
    (repo / "docs" / "specs" / "design.md").write_text("Spec design", encoding="utf-8")
    subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "docs"], check=True)

    monkeypatch.delenv("REACT_AGENT_DOCS_GIT_EXCLUDE", raising=False)
    monkeypatch.setenv("REACT_AGENT_RAG_MODE", "keyword")
    rag = RAG(save_path=str(tmp_path / "rag-index.json"))
    assert ingest_git_tracked(rag, repo, path_prefix="docs") == 1
    assert set(rag.sources) == {"git/docs/architecture/core.md"}

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    manifest_args = {
        "corpus_dir": corpus,
        "extra_dirs": [],
        "openapi_paths": [],
        "git_root": repo,
        "git_prefix": "docs",
    }
    filtered = build_manifest(**manifest_args)
    monkeypatch.setenv("REACT_AGENT_DOCS_GIT_EXCLUDE", "")
    unfiltered = build_manifest(**manifest_args)
    assert filtered["git"]["excluded_prefixes"] == ["docs/specs"]
    assert filtered["fingerprint"] != unfiltered["fingerprint"]

