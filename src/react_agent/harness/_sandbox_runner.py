"""沙箱 Runner：stdin 协议、工具白名单、结构化输出和输出上限。"""
from __future__ import annotations

import io
import json
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from typing import Any

os.environ["REACT_AGENT_SANDBOX_CHILD"] = "1"


class _LimitedBuffer(io.StringIO):
    def __init__(self, limit: int):
        super().__init__()
        self.limit = limit
        self.written = 0

    def write(self, value: str) -> int:
        text = str(value)
        remaining = max(0, self.limit - self.written)
        if remaining:
            super().write(text[:remaining])
        self.written += len(text)
        return len(text)


def _max_output() -> int:
    try:
        value = int(os.environ.get("REACT_AGENT_SANDBOX_MAX_OUTPUT", "65536"))
        return max(1024, min(value, 1048576))
    except ValueError:
        return 65536


def _max_input() -> int:
    try:
        value = int(os.environ.get("REACT_AGENT_SANDBOX_MAX_INPUT", "1048576"))
        return max(1024, min(value, 10485760))
    except ValueError:
        return 1048576


def _emit(*, ok: bool, result: str = "", error: str = "", logs: str = "") -> None:
    limit = _max_output()
    payload = {
        "ok": ok,
        "result": result[:limit],
        "error": error[:limit],
        "logs": logs[:limit],
        "truncated": any(len(item) > limit for item in (result, error, logs)),
    }
    print(json.dumps(payload, ensure_ascii=False))


def _read_call() -> dict[str, Any]:
    limit = _max_input()
    raw = sys.stdin.read(limit + 1)
    if not raw and len(sys.argv) >= 2:
        raw = sys.argv[1]
    if not raw:
        raise ValueError("缺少工具调用参数")
    if len(raw.encode("utf-8")) > limit:
        raise ValueError(f"工具调用参数超过 {limit} 字节上限")
    call = json.loads(raw)
    if not isinstance(call, dict) or not isinstance(call.get("function"), dict):
        raise ValueError("工具调用结构无效")
    return call


def main() -> int:
    try:
        tool_call = _read_call()
        name = str(tool_call["function"].get("name") or "")
        raw_arguments = tool_call["function"].get("arguments", "{}")
        arguments = (
            json.loads(raw_arguments)
            if isinstance(raw_arguments, str)
            else raw_arguments
        )
        if not isinstance(arguments, dict):
            raise ValueError("function.arguments 必须是 JSON 对象")
        allowed = {
            item.strip()
            for item in os.environ.get(
                "REACT_AGENT_SANDBOX_ALLOWED_TOOLS", ""
            ).split(",")
            if item.strip()
        }
        if not allowed or name not in allowed:
            raise PermissionError(f"工具不在本次执行白名单: {name}")
    except (
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
        PermissionError,
    ) as exc:
        _emit(ok=False, error=str(exc))
        return 2

    import_log = _LimitedBuffer(_max_output())
    try:
        with redirect_stdout(import_log), redirect_stderr(import_log):
            from react_agent.tools import TOOL_REGISTRY
    except Exception as exc:
        _emit(
            ok=False,
            error=f"工具注册表加载失败: {exc}",
            logs=import_log.getvalue(),
        )
        return 3

    if name not in TOOL_REGISTRY:
        _emit(ok=False, error=f"未知工具: {name}", logs=import_log.getvalue())
        return 4

    tool_log = _LimitedBuffer(_max_output())
    try:
        with redirect_stdout(tool_log), redirect_stderr(tool_log):
            result = TOOL_REGISTRY[name](**arguments)
        _emit(ok=True, result=str(result), logs=tool_log.getvalue())
        return 0
    except Exception as exc:
        _emit(
            ok=False,
            error=f"工具执行错误: {exc}",
            logs=tool_log.getvalue(),
        )
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
