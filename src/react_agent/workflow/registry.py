"""Workflow registry — Core declarative pipelines."""
from __future__ import annotations

from typing import Any, Optional

from react_agent.workflow.engine import (
    WorkflowDef,
    WorkflowResult,
    WorkflowRunner,
    validate_workflow,
)

_REGISTRY: dict[str, WorkflowDef] = {}


def register_workflow(wf: WorkflowDef) -> None:
    validate_workflow(wf)
    _REGISTRY[wf.name] = wf


def get_workflow(name: str) -> WorkflowDef:
    if name not in _REGISTRY:
        # Lazy-load built-ins
        _ensure_builtins()
    if name not in _REGISTRY:
        raise KeyError(f"unknown workflow: {name}. available={list_workflows()}")
    return _REGISTRY[name]


def list_workflows() -> list[dict[str, str]]:
    _ensure_builtins()
    return [
        {"name": w.name, "description": w.description, "version": w.version, "steps": str(len(w.steps))}
        for w in _REGISTRY.values()
    ]


def run_workflow(
    name: str,
    initial_state: Optional[dict[str, Any]] = None,
    tool_registry: Optional[dict] = None,
) -> WorkflowResult:
    wf = get_workflow(name)
    tools = tool_registry
    if tools is None:
        from react_agent.tools import TOOL_REGISTRY, enable_app_tools

        enable_app_tools()
        tools = TOOL_REGISTRY
    return WorkflowRunner(wf, tool_registry=tools).run(initial_state)


_BUILTINS_LOADED = False


def _ensure_builtins() -> None:
    global _BUILTINS_LOADED
    if _BUILTINS_LOADED:
        return
    from react_agent.workflow.builtins import register_builtin_workflows

    register_builtin_workflows()
    _BUILTINS_LOADED = True
