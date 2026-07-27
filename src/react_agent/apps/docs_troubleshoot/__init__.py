"""Docs / API troubleshoot application (production-oriented vertical)."""

from react_agent.apps.docs_troubleshoot.prompt import DOCS_TROUBLESHOOT_PROMPT, get_system_prompt
from react_agent.apps.docs_troubleshoot.tools import TOOL_DEFINITIONS, TOOL_REGISTRY

APP_NAME = "docs_troubleshoot"

__all__ = [
    "APP_NAME",
    "DOCS_TROUBLESHOOT_PROMPT",
    "get_system_prompt",
    "TOOL_DEFINITIONS",
    "TOOL_REGISTRY",
]
