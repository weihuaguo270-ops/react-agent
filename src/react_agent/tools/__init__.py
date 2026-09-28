"""
tools/ — 工具模块统一入口

默认只注册 Core 工具。实验工具（RAG / ToT / Dashboard）需：
  REACT_AGENT_EXPERIMENTAL_TOOLS=1
"""

from __future__ import annotations

import os
from contextvars import ContextVar
from typing import Any

from .get_time import get_time as _tool_get_time
from .get_time import TOOL_DEFINITION as _DEF_GET_TIME
from .calculator import calculator as _tool_calculator
from .calculator import TOOL_DEFINITION as _DEF_CALCULATOR
from .web_search import web_search as _tool_web_search
from .web_search import TOOL_DEFINITION as _DEF_WEB_SEARCH
from .fetch_page import fetch_page as _tool_fetch_page
from .fetch_page import TOOL_DEFINITION as _DEF_FETCH_PAGE
from .summarize import summarize as _tool_summarize
from .summarize import TOOL_DEFINITION as _DEF_SUMMARIZE
from .execute_python import execute_python as _tool_execute_python
from .execute_python import TOOL_DEFINITION as _DEF_EXECUTE_PYTHON

from react_agent.cot import tool_switch_cot_strategy, COT_TOOL_DEFINITION
from react_agent.prompts import tool_switch_role, ROLE_TOOL_DEFINITION
from react_agent.context import tool_switch_context_strategy, CONTEXT_TOOL_DEFINITION
from react_agent.harness import tool_toggle_sandbox  # noqa: F401  (host-only API)
from react_agent.harness.recorder import clear_trajectories

# ===== TOOL_REGISTRY：name → 函数（Core）=====
TOOL_REGISTRY = {
    "get_time": _tool_get_time,
    "calculator": _tool_calculator,
    "web_search": _tool_web_search,
    "fetch_page": _tool_fetch_page,
    "summarize": _tool_summarize,
    "switch_cot_strategy": tool_switch_cot_strategy,
    "switch_role": tool_switch_role,
    "switch_context_strategy": tool_switch_context_strategy,
    "clear_trajectories": clear_trajectories,
    "execute_python": _tool_execute_python,
}

# ===== TOOL_DEFINITIONS：发给 LLM 的工具描述（Core）=====
# 注意：``toggle_sandbox`` 刻意不在此列表中，也刻意不注册进 TOOL_REGISTRY 之外
# 的任何模型可见面。它属于控制面：若模型可调用，一次提示注入就能把隔离后端
# 关掉（``strategy=off``），从而让后续所有工具在宿主上直跑。需要切换策略时由
# 宿主/运维通过 ``tool_toggle_sandbox()`` 或环境变量显式完成。
# 对应守卫见 ``safety/permissions.py`` 中 toggle_sandbox 的 CONFIRM 条目。
TOOL_DEFINITIONS = [
    _DEF_WEB_SEARCH,
    _DEF_CALCULATOR,
    _DEF_FETCH_PAGE,
    _DEF_SUMMARIZE,
    _DEF_GET_TIME,
    COT_TOOL_DEFINITION,
    ROLE_TOOL_DEFINITION,
    CONTEXT_TOOL_DEFINITION,
    _DEF_EXECUTE_PYTHON,
    {
        "type": "function",
        "function": {
            "name": "clear_trajectories",
            "description": "删除历史轨迹文件，用于清理 Agent 的对话记录。支持按天数保留（如只保留最近7天）或全部删除",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "保留最近几天的文件（0=全部删除，7=保留近7天）",
                    }
                },
                "required": ["days"],
            },
        },
    },
]


def _enable_experimental_tools() -> None:
    """按需挂载 RAG / ToT / Dashboard（默认关闭，避免叙事与默认面混杂）。"""
    if os.environ.get("REACT_AGENT_EXPERIMENTAL_TOOLS", "").strip().lower() not in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return
    from .dashboard import start_dashboard as _tool_start_dashboard
    from .dashboard import TOOL_DEFINITION as _DEF_DASHBOARD
    from react_agent.rag import rag_query, RAG_TOOL_DEFINITION
    from react_agent.tot import tool_tot_reasoning, TOT_TOOL_DEFINITION

    TOOL_REGISTRY["rag_query"] = rag_query
    TOOL_REGISTRY["tot_reasoning"] = tool_tot_reasoning
    TOOL_REGISTRY["start_dashboard"] = _tool_start_dashboard
    for defn in (RAG_TOOL_DEFINITION, TOT_TOOL_DEFINITION, _DEF_DASHBOARD):
        if defn not in TOOL_DEFINITIONS:
            TOOL_DEFINITIONS.append(defn)


_enable_experimental_tools()


def enable_app_tools() -> None:
    """Mount vertical-app tools when REACT_AGENT_APP is set (idempotent).

    ⚠️ 这会**永久**修改全局 ``TOOL_REGISTRY`` / ``TOOL_DEFINITIONS``：一旦某个
    垂直应用的工具被挂载，进程内所有应用都会看到它们。请求路径应改用
    ``set_request_app()`` + ``get_registry()`` / ``get_tool_definitions()``
    以获得应用作用域隔离。
    """
    from react_agent.apps import load_app_tools

    registry, defs = load_app_tools()
    if not registry:
        return
    TOOL_REGISTRY.update(registry)
    for defn in defs:
        names = {d["function"]["name"] for d in TOOL_DEFINITIONS if "function" in d}
        if defn["function"]["name"] not in names:
            TOOL_DEFINITIONS.append(defn)


# 应用作用域工具视图（不污染全局）
# app 工具此前经 enable_app_tools() 并入全局注册表，导致 docs_troubleshoot 的
# 工具（search_docs / probe_service_health / read_config_snapshot …）对其他应用
# 也可见可调。这里用请求级 ContextVar 表达「本次请求属于哪个 app」，
# react_loop / agent_runner 据此取到**隔离**的注册表与工具描述。
#
# 注意：仍有遗留调用方会执行 enable_app_tools() 把 app 工具永久并入全局表
# （例如 CLI main() 或某些测试）。为了让隔离不被这种污染破坏，这里在模块末尾
# 固化一份「Core 工具」名单，Core 作用域只按该名单投影全局表。
_ACTIVE_TOOLS_APP: ContextVar[str] = ContextVar("react_agent_tools_app", default="")
_CORE_TOOL_NAMES: frozenset[str] = frozenset()


def set_request_app(app: str | None) -> None:
    """声明本次请求的垂直应用（空值表示 Core 通用应用）。"""
    _ACTIVE_TOOLS_APP.set((app or "").strip().lower())


def active_tools_app() -> str:
    return _ACTIVE_TOOLS_APP.get()


def _app_registry_and_defs(app: str) -> tuple[dict[str, Any], list[dict]]:
    if app not in ("docs_troubleshoot", "docs"):
        return {}, []
    from react_agent.apps.docs_troubleshoot import (
        TOOL_DEFINITIONS as DOCS_DEFS,
        TOOL_REGISTRY as DOCS_REGISTRY,
    )

    return dict(DOCS_REGISTRY), list(DOCS_DEFS)


def _core_registry() -> dict[str, Any]:
    """仅含 Core 工具的注册表投影（剔除被并入全局表的 app 工具）。"""
    return {
        name: fn
        for name, fn in TOOL_REGISTRY.items()
        if not _CORE_TOOL_NAMES or name in _CORE_TOOL_NAMES
    }


def _core_definitions() -> list[dict]:
    """仅含 Core 工具的描述列表。"""
    if not _CORE_TOOL_NAMES:
        return list(TOOL_DEFINITIONS)
    return [
        d for d in TOOL_DEFINITIONS
        if d.get("function", {}).get("name") in _CORE_TOOL_NAMES
    ]


def get_registry(app: str | None = None) -> dict[str, Any]:
    """返回 Core 工具 + 指定应用工具的合并视图（不改动全局对象）。"""
    target = (app if app is not None else active_tools_app()).strip().lower()
    merged: dict[str, Any] = _core_registry()
    extra, _ = _app_registry_and_defs(target)
    merged.update(extra)
    return merged


def get_tool_definitions(app: str | None = None) -> list[dict]:
    """返回当前应用应有的工具描述列表（不读全局 TOOL_DEFINITIONS）。"""
    target = (app if app is not None else active_tools_app()).strip().lower()
    defs = _core_definitions()
    names = {d["function"]["name"] for d in defs if "function" in d}
    _, extra = _app_registry_and_defs(target)
    for defn in extra:
        name = defn.get("function", {}).get("name")
        if name and name not in names:
            defs.append(defn)
            names.add(name)
    return defs


enable_app_tools()


def enable_workflow_tools() -> None:
    """Core Workflow tools are always-on (self-built orchestration surface)."""
    from react_agent.workflow.tools import WORKFLOW_TOOL_DEFINITIONS, WORKFLOW_TOOL_REGISTRY

    TOOL_REGISTRY.update(WORKFLOW_TOOL_REGISTRY)
    names = {d["function"]["name"] for d in TOOL_DEFINITIONS if "function" in d}
    for defn in WORKFLOW_TOOL_DEFINITIONS:
        if defn["function"]["name"] not in names:
            TOOL_DEFINITIONS.append(defn)


def _all_app_tool_names() -> set[str]:
    """所有可能被并入全局表的 app 层工具名（用于把它们排除出 Core 视图）。"""
    names: set[str] = set()
    try:
        from react_agent.apps.docs_troubleshoot import TOOL_REGISTRY as DOCS_REG

        names.update(DOCS_REG)
    except Exception:
        pass
    return names


def _freeze_core_tools() -> None:
    """模块装配完成后固化 Core 工具名单，避免 app 工具污染 Core 视图。"""
    global _CORE_TOOL_NAMES
    app_names = _all_app_tool_names()
    _CORE_TOOL_NAMES = frozenset(
        name for name in TOOL_REGISTRY if name not in app_names
    )


enable_workflow_tools()
_freeze_core_tools()
