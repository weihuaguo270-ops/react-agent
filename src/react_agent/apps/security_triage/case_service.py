"""Application service for persistent triage cases."""
from __future__ import annotations

from typing import Any

from .case_store import SecurityCaseStore
from .workflow import run_triage


def create_security_case(store: SecurityCaseStore, body: dict[str, Any]) -> dict[str, Any]:
    """Analyze and persist a new case, always starting in pending review."""
    if body.get("review") is not None:
        raise ValueError("review is not accepted during case creation; use the review endpoint")
    result = run_triage(body)
    return store.create(body, result)
