"""Centralized temporary directory management.

All temporary files should be created under .cache/tmp/ to avoid polluting
the repository root.
"""
import os
from pathlib import Path
from typing import Optional

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent

# 统一的临时目录基路径
TEMP_BASE_DIR = PROJECT_ROOT / ".cache" / "tmp"


def get_temp_dir(subdir: Optional[str] = None) -> Path:
    """Get a temporary directory path, creating it if needed.

    Args:
        subdir: Optional subdirectory name under .cache/tmp/

    Returns:
        Path to the temporary directory
    """
    if subdir:
        temp_dir = TEMP_BASE_DIR / subdir
    else:
        temp_dir = TEMP_BASE_DIR

    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir


def get_pytest_temp_dir() -> Path:
    """Get pytest temporary directory."""
    return get_temp_dir("pytest")


def get_evidence_temp_dir() -> Path:
    """Get evidence temporary directory."""
    return get_temp_dir("evidence")


def get_release_temp_dir(identifier: str = "default") -> Path:
    """Get release temporary directory.

    Args:
        identifier: Unique identifier for this release temp dir
    """
    return get_temp_dir(f"release-{identifier}")


def get_pr_temp_dir(pr_number: int, date: Optional[str] = None) -> Path:
    """Get PR-specific temporary directory.

    Args:
        pr_number: Pull request number
        date: Optional date string (YYYYMMDD format)
    """
    if date:
        subdir = f"pr{pr_number}-{date}"
    else:
        subdir = f"pr{pr_number}"
    return get_temp_dir(subdir)


def cleanup_temp_dirs(keep_recent: int = 1) -> None:
    """Clean up old temporary directories.

    Args:
        keep_recent: Number of recent temp dirs to keep for each category
    """
    import shutil
    from datetime import datetime

    if not TEMP_BASE_DIR.exists():
        return

    # Group directories by prefix
    categories: dict[str, list[tuple[Path, float]]] = {}

    for item in TEMP_BASE_DIR.iterdir():
        if not item.is_dir():
            continue

        # Extract category prefix (e.g., "pytest", "pr", "release")
        parts = item.name.split("-", 1)
        category = parts[0]

        mtime = item.stat().st_mtime
        categories.setdefault(category, []).append((item, mtime))

    # Sort by modification time and remove old ones
    for category, dirs in categories.items():
        # Sort by mtime, newest first
        dirs.sort(key=lambda x: x[1], reverse=True)

        # Keep only recent ones
        for path, _ in dirs[keep_recent:]:
            print(f"Removing old temp dir: {path.relative_to(PROJECT_ROOT)}")
            shutil.rmtree(path, ignore_errors=True)
