"""Stable hashes for text evidence across checkout newline policies."""

from __future__ import annotations

import hashlib
from pathlib import Path


def canonical_bytes(path: Path) -> bytes:
    """Normalize text newlines before hashing evidence files."""

    return path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(canonical_bytes(path))
