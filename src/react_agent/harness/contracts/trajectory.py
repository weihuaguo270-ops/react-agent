"""Canonical Format B trajectory serializer used by all adapters."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from .parser import SCHEMA_VERSION, assert_valid, normalize_trajectory


def serialize_trajectory(
    *,
    session_id: str,
    query: str,
    steps: Sequence[Mapping[str, Any]],
    final_answer: str = "",
    model: str = "",
    metadata: Mapping[str, Any] | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build, normalize and validate a Format B trajectory in one place.

    ``extra`` contains contract-approved top-level fields such as episode and
    artifact metadata. Keeping those fields here prevents individual recorders
    from creating a second wire format while retaining compatibility fields.
    """
    raw: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "query": query,
        "model": model,
        "final_answer": final_answer,
        "steps": [dict(step) for step in steps],
        "metadata": dict(metadata or {}),
    }
    if extra:
        raw.update(dict(extra))
    result = normalize_trajectory(raw)
    assert_valid(result)
    return result


__all__ = ["serialize_trajectory"]
