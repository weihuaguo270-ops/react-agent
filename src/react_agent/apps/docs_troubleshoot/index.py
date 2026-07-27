"""Corpus index for docs/API troubleshoot app (keyword-first, CI-friendly)."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from react_agent.rag import RAG

_CORPUS_DIR = Path(__file__).resolve().parent / "corpus"


def corpus_dir() -> Path:
    return _CORPUS_DIR


@lru_cache(maxsize=1)
def get_index() -> RAG:
    """Load corpus into an isolated RAG index (not the global RAG_INDEX)."""
    os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")
    save = Path(__file__).resolve().parent / "_index_cache.json"
    rag = RAG(save_path=str(save))
    rag.clear()
    rag.ingest_directory(str(_CORPUS_DIR))
    return rag


def reset_index() -> RAG:
    get_index.cache_clear()
    return get_index()
