"""Portable locations for mutable Agent runtime data."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def data_dir() -> Path:
    """Return the writable application data directory without touching the source tree."""
    override = os.environ.get("REACT_AGENT_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / "react-agent"
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg).expanduser() / "react-agent"
    return Path.home() / ".local" / "share" / "react-agent"


def runtime_dir(kind: str, *, env_var: str | None = None) -> Path:
    """Resolve a mutable artifact directory with an optional dedicated override."""
    if env_var and os.environ.get(env_var):
        return Path(os.environ[env_var]).expanduser().resolve()
    return data_dir() / kind


def runtime_file(name: str, *, env_var: str | None = None) -> Path:
    """Resolve a mutable artifact file with an optional dedicated override."""
    if env_var and os.environ.get(env_var):
        return Path(os.environ[env_var]).expanduser().resolve()
    return data_dir() / name


def migrate_legacy_file(target: Path, legacy: Path) -> Path:
    """Copy a legacy package-local data file once when the new target is empty."""
    if target.exists() or not legacy.is_file() or target == legacy:
        return target
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy, target)
    except OSError:
        pass
    return target
