"""Application registry — enable vertical apps via REACT_AGENT_APP."""
from __future__ import annotations

import os
from typing import Optional


def active_app() -> str:
    return os.environ.get("REACT_AGENT_APP", "").strip().lower()


def is_docs_troubleshoot() -> bool:
    return active_app() in ("docs_troubleshoot", "docs", "1")


def load_app_tools() -> tuple[dict, list]:
    """Return (registry_updates, tool_definitions) for the active app."""
    if not is_docs_troubleshoot():
        return {}, []
    from react_agent.apps.docs_troubleshoot import TOOL_DEFINITIONS, TOOL_REGISTRY

    return dict(TOOL_REGISTRY), list(TOOL_DEFINITIONS)


def app_system_prompt(question: str = "") -> Optional[str]:
    if not is_docs_troubleshoot():
        return None
    from react_agent.apps.docs_troubleshoot.prompt import get_system_prompt

    return get_system_prompt(question)
