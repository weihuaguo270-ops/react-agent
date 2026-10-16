"""Canonical Format B parser API for Shared Contracts.

The implementation remains backed by the legacy schema checker during the
compatibility period. New Runtime, Evaluation, and adapter code should import
these functions from ``react_agent.harness.contracts``; ``harness.schema`` is
kept only for existing public callers.
"""
from __future__ import annotations

import json
from os import PathLike
from pathlib import Path
from typing import Any, Mapping

from ..schema import (
    SCHEMA_VERSION,
    TrajectorySchemaError,
    assert_valid as _assert_valid,
    normalize_trajectory as _normalize_trajectory,
    validate_trajectory as _validate_trajectory,
)


def validate_trajectory(
    data: Mapping[str, Any], *, strict_one_based: bool = True
) -> list[str]:
    """Validate a Format B mapping using the shared contract checker."""
    return _validate_trajectory(dict(data), strict_one_based=strict_one_based)


def normalize_trajectory(data: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize a legacy or current Format B mapping."""
    return _normalize_trajectory(dict(data))


def assert_valid(
    data: Mapping[str, Any], *, strict_one_based: bool = True
) -> dict[str, Any]:
    """Validate a mapping and return it, raising the shared schema error."""
    return _assert_valid(dict(data), strict_one_based=strict_one_based)


def parse_trajectory(
    value: Mapping[str, Any] | str | PathLike[str],
    *,
    strict_one_based: bool = True,
) -> dict[str, Any]:
    """Parse, normalize, and validate one Format B trajectory.

    ``value`` may be a mapping, a JSON document string, or a filesystem path.
    Normalization happens before validation so legacy ``args`` and omitted
    schema versions receive the same compatibility behavior everywhere.
    """
    if isinstance(value, Mapping):
        raw = dict(value)
    elif isinstance(value, PathLike):
        raw = json.loads(Path(value).read_text(encoding="utf-8"))
    elif isinstance(value, str):
        try:
            candidate = Path(value)
            is_file = candidate.is_file()
        except OSError:
            is_file = False
        raw = (
            json.loads(candidate.read_text(encoding="utf-8"))
            if is_file
            else json.loads(value)
        )
    else:
        raise TypeError("trajectory must be a mapping, JSON string, or path")
    normalized = normalize_trajectory(raw)
    return assert_valid(normalized, strict_one_based=strict_one_based)


def load_and_validate(filepath: str | PathLike[str]) -> dict[str, Any]:
    """Compatibility name for callers that explicitly load a file."""
    return parse_trajectory(filepath)


__all__ = [
    "SCHEMA_VERSION",
    "TrajectorySchemaError",
    "assert_valid",
    "load_and_validate",
    "normalize_trajectory",
    "parse_trajectory",
    "validate_trajectory",
]
