"""Material ingest: directories, OpenAPI specs, incremental manifest."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from react_agent.rag import RAG

_MANIFEST_VERSION = 2
_DOC_SUFFIXES = {".md", ".txt", ".yaml", ".yml", ".json"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _source_label(root: Path, fp: Path) -> str:
    try:
        rel = fp.relative_to(root)
        return f"{root.name}/{rel.as_posix()}"
    except ValueError:
        return fp.name


def _iter_doc_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    files: list[Path] = []
    for fp in sorted(root.rglob("*")):
        if not fp.is_file():
            continue
        if fp.suffix.lower() not in _DOC_SUFFIXES:
            continue
        if fp.name.startswith("_index"):
            continue
        files.append(fp)
    return files


def _collect_doc_files(*roots: Path) -> dict[str, str]:
    """Map relative-ish source label -> sha256 (recursive tree walk)."""
    out: dict[str, str] = {}
    for root in roots:
        for fp in _iter_doc_files(root):
            out[_source_label(root, fp)] = sha256_file(fp)
    return out


def _resolve_ref(spec: dict[str, Any], ref: str) -> dict[str, Any]:
    if not ref.startswith("#/"):
        return {}
    node: Any = spec
    for part in ref.lstrip("#/").split("/"):
        if not isinstance(node, dict):
            return {}
        node = node.get(part, {})
    return node if isinstance(node, dict) else {}


def ingest_tree(rag: RAG, root: Path, *, label_prefix: str | None = None) -> int:
    """Recursively ingest supported docs under root with stable source labels."""
    if not root.is_dir():
        return 0
    prefix = label_prefix or root.name
    count = 0
    for fp in _iter_doc_files(root):
        rel = fp.relative_to(root)
        source = f"{prefix}/{rel.as_posix()}"
        text = fp.read_text(encoding="utf-8", errors="ignore")
        if text.strip() and rag.ingest_text(text, source=source):
            count += 1
    return count


def ingest_git_tracked(
    rag: RAG,
    repo: Path,
    *,
    path_prefix: str = "",
) -> int:
    """Ingest git-tracked doc files from a repository (ls-files)."""
    if not (repo / ".git").exists() and not (repo / ".git").is_file():
        try:
            subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "--git-dir"],
                capture_output=True,
                check=True,
                timeout=15,
            )
        except (subprocess.SubprocessError, OSError):
            return 0
    cmd = ["git", "-C", str(repo), "ls-files"]
    if path_prefix:
        cmd.extend(["--", path_prefix])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=30)
    except (subprocess.SubprocessError, OSError):
        return 0
    if proc.returncode != 0:
        return 0
    count = 0
    for line in proc.stdout.splitlines():
        rel = line.strip().replace("\\", "/")
        if not rel:
            continue
        fp = repo / rel
        if not fp.is_file() or fp.suffix.lower() not in _DOC_SUFFIXES:
            continue
        if fp.name.startswith("_index"):
            continue
        text = fp.read_text(encoding="utf-8", errors="ignore")
        if text.strip() and rag.ingest_text(text, source=f"git/{rel}"):
            count += 1
    return count


def openapi_to_chunks(spec: dict[str, Any], source: str) -> list[tuple[str, str]]:
    """Flatten OpenAPI paths into searchable text chunks."""
    chunks: list[tuple[str, str]] = []
    paths = spec.get("paths") or {}
    if not isinstance(paths, dict):
        return chunks
    for path, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        for method, detail in methods.items():
            if method.startswith("x-") or not isinstance(detail, dict):
                continue
            lines = [
                f"OpenAPI {method.upper()} {path}",
                f"summary: {detail.get('summary', '')}",
            ]
            for code, resp in (detail.get("responses") or {}).items():
                if isinstance(resp, dict):
                    if "$ref" in resp:
                        resp = _resolve_ref(spec, str(resp["$ref"]))
                    desc = resp.get("description", "")
                    schema = resp.get("schema") or {}
                    if isinstance(schema, dict) and "$ref" in schema:
                        schema = _resolve_ref(spec, str(schema["$ref"]))
                    if isinstance(schema, dict) and schema.get("properties"):
                        props = ", ".join(sorted(schema["properties"].keys())[:8])
                        desc = f"{desc} schema={props}".strip()
                    lines.append(f"HTTP {code}: {desc}")
            for param in detail.get("parameters") or []:
                if isinstance(param, dict):
                    lines.append(
                        f"param {param.get('name')} in={param.get('in')} "
                        f"schema={param.get('schema', {})}"
                    )
            text = "\n".join(lines)
            chunks.append((text, f"{source}#{method.upper()} {path}"))
    return chunks


def ingest_openapi(rag: RAG, path: Path) -> int:
    raw = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore

            spec = yaml.safe_load(raw)
        except Exception:
            return 0
    else:
        spec = json.loads(raw)
    if not isinstance(spec, dict):
        return 0
    added = 0
    for text, src in openapi_to_chunks(spec, path.name):
        if rag.ingest_text(text, source=f"openapi/{src}"):
            added += 1
    return added


def git_ingest_from_env() -> tuple[Path | None, str]:
    raw = os.environ.get("REACT_AGENT_DOCS_GIT_ROOT", "").strip()
    if not raw:
        return None, ""
    prefix = os.environ.get("REACT_AGENT_DOCS_GIT_PREFIX", "docs").strip()
    return Path(raw), prefix


def build_manifest(
    *,
    corpus_dir: Path,
    extra_dirs: list[Path],
    openapi_paths: list[Path],
    git_root: Path | None = None,
    git_prefix: str = "",
) -> dict[str, Any]:
    files = _collect_doc_files(corpus_dir, *extra_dirs)
    git_meta: dict[str, Any] = {}
    if git_root and git_root.is_dir():
        git_meta = {"root": str(git_root), "prefix": git_prefix}
    openapi_meta: dict[str, Any] = {}
    for p in openapi_paths:
        if p.is_file():
            openapi_meta[p.name] = {"sha256": sha256_file(p)}
    fingerprint = hashlib.sha256(
        json.dumps(
            {"files": files, "openapi": openapi_meta, "git": git_meta},
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return {
        "version": _MANIFEST_VERSION,
        "fingerprint": fingerprint,
        "files": files,
        "openapi": openapi_meta,
        "git": git_meta,
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def rebuild_index(
    rag: RAG,
    *,
    corpus_dir: Path,
    extra_dirs: list[Path] | None = None,
    openapi_paths: list[Path] | None = None,
    git_root: Path | None = None,
    git_prefix: str = "",
) -> dict[str, Any]:
    extra_dirs = extra_dirs or []
    openapi_paths = openapi_paths or []
    rag.clear()
    ingest_tree(rag, corpus_dir, label_prefix=corpus_dir.name)
    for root in extra_dirs:
        ingest_tree(rag, root, label_prefix=root.name)
    if git_root:
        ingest_git_tracked(rag, git_root, path_prefix=git_prefix)
    for op in openapi_paths:
        if op.is_file():
            ingest_openapi(rag, op)
    return build_manifest(
        corpus_dir=corpus_dir,
        extra_dirs=extra_dirs,
        openapi_paths=openapi_paths,
        git_root=git_root,
        git_prefix=git_prefix,
    )


def extra_ingest_dirs_from_env() -> list[Path]:
    raw = os.environ.get("REACT_AGENT_DOCS_INGEST_DIRS", "").strip()
    if not raw:
        return []
    return [Path(p.strip()) for p in raw.split(",") if p.strip()]


def openapi_paths_from_env(app_dir: Path) -> list[Path]:
    paths: list[Path] = []
    env = os.environ.get("REACT_AGENT_OPENAPI_SPEC", "").strip()
    if env:
        paths.append(Path(env))
    repo_root = app_dir.resolve().parents[3]
    default = repo_root / "fixtures" / "docs_troubleshoot" / "openapi_sample.json"
    if default.is_file() and default not in paths:
        paths.append(default)
    return [p for p in paths if p.is_file()]
