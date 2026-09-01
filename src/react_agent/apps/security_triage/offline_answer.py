"""Chat-router adapter for the Security Triage Agent."""
from __future__ import annotations

from typing import Any

from .workflow import run_triage


def answer_offline(body: dict[str, Any]) -> dict[str, Any]:
    """Return a stable error contract or a citation-backed triage case."""
    try:
        output = run_triage(body)
    except ValueError as exc:
        return {
            "ok": False,
            "app": "security_triage",
            "answer": str(exc),
            "error_code": "invalid_security_triage_request",
        }
    return {
        "ok": True,
        "app": "security_triage",
        "mode": output["case"]["mode"],
        **output,
    }
