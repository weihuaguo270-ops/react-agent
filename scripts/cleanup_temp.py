#!/usr/bin/env python3
"""Clean up temporary directories in the project."""
import argparse
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def cleanup_temp_dirs(dry_run: bool = False, keep_cache: bool = False):
    """Clean up all temporary directories.

    Args:
        dry_run: If True, only print what would be deleted
        keep_cache: If True, keep .cache/ directory structure
    """
    # Patterns for temporary directories to remove
    temp_patterns = [
        ".pytest-tmp*",
        ".tmp-*",
        ".evidence_tmp",
        ".release-*",
        ".pytest-basetemp",
    ]

    removed_count = 0

    print("Scanning for temporary directories...")

    for pattern in temp_patterns:
        for path in PROJECT_ROOT.glob(pattern):
            if path.is_dir():
                if dry_run:
                    print(f"Would remove: {path.relative_to(PROJECT_ROOT)}")
                else:
                    print(f"Removing: {path.relative_to(PROJECT_ROOT)}")
                    shutil.rmtree(path, ignore_errors=True)
                removed_count += 1

    # Clean up .cache/tmp/ if not keeping cache
    cache_tmp = PROJECT_ROOT / ".cache" / "tmp"
    if cache_tmp.exists() and not keep_cache:
        if dry_run:
            print(f"Would remove: {cache_tmp.relative_to(PROJECT_ROOT)}")
        else:
            print(f"Removing: {cache_tmp.relative_to(PROJECT_ROOT)}")
            shutil.rmtree(cache_tmp, ignore_errors=True)
        removed_count += 1

    if removed_count == 0:
        print("No temporary directories found.")
    else:
        action = "Would remove" if dry_run else "Removed"
        print(f"\n{action} {removed_count} temporary director{'y' if removed_count == 1 else 'ies'}.")


def main():
    parser = argparse.ArgumentParser(description="Clean up temporary directories")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without actually deleting"
    )
    parser.add_argument(
        "--keep-cache",
        action="store_true",
        help="Keep .cache/tmp/ structure (only clean root-level temp dirs)"
    )

    args = parser.parse_args()
    cleanup_temp_dirs(dry_run=args.dry_run, keep_cache=args.keep_cache)


if __name__ == "__main__":
    main()
