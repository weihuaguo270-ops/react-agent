"""RAG keyword offline path — no sentence-transformers required."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from react_agent.rag import RAG


@pytest.fixture()
def corpus_dir():
    root = Path(__file__).resolve().parents[1] / "fixtures" / "rag_corpus"
    assert root.is_dir()
    return root


def test_keyword_ingest_and_query(tmp_path, monkeypatch, corpus_dir):
    monkeypatch.setenv("REACT_AGENT_RAG_MODE", "keyword")
    rag = RAG(save_path=str(tmp_path / "idx.json"))
    rag.clear()
    n = rag.ingest_directory(str(corpus_dir))
    assert n >= 1
    assert rag.chunks

    hits = rag.query("报销额度 餐饮", top_k=3)
    assert hits, "应命中 expense_policy 片段"
    blob = " ".join(h["content"] for h in hits)
    assert "餐饮" in blob or "200" in blob

    hits2 = rag.query("API Key 配置", top_k=3)
    assert hits2
    assert any("API" in h["content"] or "Key" in h["content"] or ".env" in h["content"] for h in hits2)


def test_rag_query_tool_empty_index(tmp_path, monkeypatch):
    monkeypatch.setenv("REACT_AGENT_RAG_MODE", "keyword")
    # 独立实例，不污染全局 RAG_INDEX
    rag = RAG(save_path=str(tmp_path / "empty.json"))
    rag.chunks = []
    rag.sources = []
    rag.vecs = []
    assert rag.query("anything") == []
