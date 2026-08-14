"""Portable locations for mutable Agent runtime data."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


def _platform_name() -> str:
    """Return the runtime platform name through a testable local boundary."""
    return os.name


def data_dir() -> Path:
    """Return the writable application data directory without touching the source tree."""
    override = os.environ.get("REACT_AGENT_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if _platform_name() == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            candidate = Path(base) / "react-agent"
            if _directory_is_writable(candidate):
                return candidate
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg).expanduser() / "react-agent"
    candidate = Path.home() / ".local" / "share" / "react-agent"
    if _directory_is_writable(candidate):
        return candidate
    return Path(tempfile.gettempdir()) / "react-agent"


def _directory_is_writable(path: Path) -> bool:
    """Check the resolved default once so restricted hosts still have a usable path."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-check"
        probe.touch()
        probe.unlink()
        return True
    except OSError:
        return False


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
