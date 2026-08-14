"""无需 LLM 的确定性 ReAct 冒烟路径。"""
from __future__ import annotations

import re
from typing import Any

from react_agent.eval.execution_scorer import execute_tool_step


def _extract_calculator_expression(message: str) -> str | None:
    """从受支持的中英文表达中提取简单二元算式。"""
    text = message.replace("×", "*").replace("x", "*").replace("X", "*")
    # Explicit expression like 17*19 or 100 - 37
    m = re.search(
        r"(\d+(?:\.\d+)?)\s*([+\-*/])\s*(\d+(?:\.\d+)?)",
        text,
    )
    if m:
        return f"{m.group(1)} {m.group(2)} {m.group(3)}"
    # Chinese: 17 乘以 19 / 8 乘以 7
    m = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:乘以|乘)\s*(\d+(?:\.\d+)?)",
        message,
    )
    if m:
        return f"{m.group(1)} * {m.group(2)}"
    m = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:减去|减)\s*(\d+(?:\.\d+)?)",
        message,
    )
    if m:
        return f"{m.group(1)} - {m.group(2)}"
    return None


def _python_snippet_for_message(message: str) -> str | None:
    """将固定冒烟问题映射为可控 Python 片段。"""
    if "1+2+3+4+5" in message or "1+2+3+4+5" in message.replace(" ", ""):
        return "print(sum(range(1, 6)))"
    if "阶乘" in message and "5" in message:
        return "import math\nprint(math.factorial(5))"
    if "2 的 8 次方" in message or "2**8" in message or "2 的八次方" in message:
        return "print(2 ** 8)"
    return None


def offline_react_loop(message: str, *, max_steps: int = 6) -> dict[str, Any]:
    """运行最小工具循环并返回答案、工具清单和步骤。"""
    steps: list[dict[str, Any]] = []
    tools_called: list[str] = []

    def _call(tool: str, arguments: dict[str, Any]) -> str:
        """执行一步并同步记录可评测轨迹。"""
        obs = execute_tool_step(tool, arguments)
        tools_called.append(tool)
        steps.append({"tool": tool, "arguments": arguments, "observation": obs[:500]})
        return obs

    lower = message.lower()
    answer = ""

    if "get_time" in lower or "当前时间" in message or "查询当前时间" in message:
        obs = _call("get_time", {})
        answer = f"当前时间是 {obs.strip()}。"

    elif "execute_python" in lower or "写代码" in message:
        code = _python_snippet_for_message(message)
        if code:
            obs = _call("execute_python", {"code": code})
            answer = f"执行结果是 {obs.strip()}。"

    elif "calculator" in lower or "计算" in message:
        expr = _extract_calculator_expression(message)
        if expr:
            obs = _call("calculator", {"expression": expr})
            answer = f"计算结果是 {obs.strip()}。"

    # 不支持的问题显式失败，避免把规则路径误报为通用 Agent 能力。
    if not answer:
        return {
            "ok": False,
            "answer": "offline_react: unsupported smoke query",
            "tools_called": tools_called,
            "agent_steps": steps,
        }

    return {
        "ok": True,
        "answer": answer,
        "tools_called": tools_called,
        "agent_steps": steps,
        "mode": "offline_react",
    }
