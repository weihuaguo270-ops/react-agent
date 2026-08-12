"""统一执行 required 模式下的本地工具安全边界。"""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

from react_agent.harness.sandbox import SANDBOX
from react_agent.safety.permission_gate import permission_block_message


def execute_registered_tool(
    tool_name: str,
    arguments: dict[str, Any],
    registry: Mapping[str, Callable[..., Any]],
) -> Any:
    """开发模式直调；required 模式强制权限闸门和容器后端。"""
    fn = registry.get(tool_name)
    if fn is None:
        raise KeyError(f"tool not found: {tool_name}")

    if not SANDBOX.required:
        return fn(**arguments)

    blocked = permission_block_message(tool_name, arguments)
    if blocked is not None:
        raise PermissionError(blocked)

    tool_call = {
        "function": {
            "name": tool_name,
            "arguments": json.dumps(arguments, ensure_ascii=False),
        }
    }
    result = SANDBOX.run(tool_call)
    if result == "__SANDBOX_DISABLED__":
        raise RuntimeError("required 模式拒绝未隔离工具执行")
    if result.startswith("[沙箱]"):
        raise RuntimeError(result)
    return result
