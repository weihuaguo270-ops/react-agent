"""Agent-callable tools for Core Workflow."""
from __future__ import annotations

import json
from typing import Any

from react_agent.workflow.registry import list_workflows, run_workflow


def list_workflows_tool() -> str:
    """List registered Core workflows."""
    return json.dumps({"workflows": list_workflows()}, ensure_ascii=False)


def run_workflow_tool(name: str, query: str = "", payload_json: str = "") -> str:
    """
    Run a named Core workflow.
    Prefer query= for docs_troubleshoot; or payload_json for full initial state.
    """
    initial: dict[str, Any] = {}
    if payload_json and payload_json.strip():
        try:
            initial = json.loads(payload_json)
        except json.JSONDecodeError as e:
            return json.dumps({"ok": False, "error": f"invalid payload_json: {e}"})
    if query:
        initial.setdefault("query", query)
    if not initial.get("query") and name == "docs_troubleshoot":
        return json.dumps({"ok": False, "error": "query is required"})

    # Ensure docs app tools exist when running docs workflow
    if name == "docs_troubleshoot":
        import os

        os.environ.setdefault("REACT_AGENT_APP", "docs_troubleshoot")
        os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")
        from react_agent.tools import enable_app_tools

        enable_app_tools()
        from react_agent.apps.docs_troubleshoot.index import reset_index

        reset_index()

    result = run_workflow(name, initial)
    data = result.to_dict()
    data["ok"] = result.ok
    data["answer"] = result.answer
    data["refused"] = result.refused
    data["citations"] = result.citations
    data["diagnosis"] = result.diagnosis
    return json.dumps(data, ensure_ascii=False)


LIST_WORKFLOWS_DEF = {
    "type": "function",
    "function": {
        "name": "list_workflows",
        "description": "列出已注册的 Core Workflow（确定性多步流水线）",
        "parameters": {"type": "object", "properties": {}},
    },
}

RUN_WORKFLOW_DEF = {
    "type": "function",
    "function": {
        "name": "run_workflow",
        "description": (
            "运行命名 Workflow。文档排障请用 name=docs_troubleshoot 并传 query。"
            "比自由 ReAct 更可控、可审计。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "workflow 名称"},
                "query": {"type": "string", "description": "用户问题（写入 state.query）"},
                "payload_json": {
                    "type": "string",
                    "description": "可选，完整 initial state 的 JSON 字符串",
                },
            },
            "required": ["name"],
        },
    },
}

WORKFLOW_TOOL_DEFINITIONS = [LIST_WORKFLOWS_DEF, RUN_WORKFLOW_DEF]
WORKFLOW_TOOL_REGISTRY = {
    "list_workflows": list_workflows_tool,
    "run_workflow": run_workflow_tool,
}
