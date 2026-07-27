"""Corpus index for docs/API troubleshoot (keyword-first, incremental manifest)."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from react_agent.apps.docs_troubleshoot.ingest import (
    extra_ingest_dirs_from_env,
    git_ingest_from_env,
    openapi_paths_from_env,
    rebuild_index,
)
from react_agent.rag import RAG

_CORPUS_DIR = Path(__file__).resolve().parent / "corpus"
_APP_DIR = Path(__file__).resolve().parent
_MANIFEST_PATH = _APP_DIR / "_index_manifest.json"
_CACHE_PATH = _APP_DIR / "_index_cache.json"


def corpus_dir() -> Path:
    return _CORPUS_DIR


def _openapi_paths() -> list[Path]:
    if os.environ.get("REACT_AGENT_INGEST_OPENAPI", "").strip().lower() not in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return []
    return openapi_paths_from_env(_APP_DIR)


@lru_cache(maxsize=1)
def get_index() -> RAG:
    """Load corpus + optional extra dirs / OpenAPI into isolated RAG index."""
    os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")
    extra = extra_ingest_dirs_from_env()
    openapi = _openapi_paths()
    git_root, git_prefix = git_ingest_from_env()
    rag = RAG(save_path=str(_CACHE_PATH))

    from react_agent.apps.docs_troubleshoot.ingest import build_manifest

    target_fp = build_manifest(
        corpus_dir=_CORPUS_DIR,
        extra_dirs=extra,
        openapi_paths=openapi,
        git_root=git_root,
        git_prefix=git_prefix,
    ).get("fingerprint")

    if _MANIFEST_PATH.is_file() and rag.chunks:
        try:
            stored = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
            if stored.get("fingerprint") == target_fp:
                return rag
        except (json.JSONDecodeError, OSError):
            pass

    manifest = rebuild_index(
        rag,
        corpus_dir=_CORPUS_DIR,
        extra_dirs=extra,
        openapi_paths=openapi,
        git_root=git_root,
        git_prefix=git_prefix,
    )
    _MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return rag


def reset_index() -> RAG:
    get_index.cache_clear()
    if _MANIFEST_PATH.is_file():
        try:
            _MANIFEST_PATH.unlink()
        except OSError:
            pass
    if _CACHE_PATH.is_file():
        try:
            _CACHE_PATH.unlink()
        except OSError:
            pass
    return get_index()
