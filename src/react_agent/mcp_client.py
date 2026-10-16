
"""
MCP Client — 独立的 MCP 协议实现模块
======================================
纯 Python，仅依赖标准库（json + subprocess）
任何 Agent 都可以 import 使用

用法:
    from react_agent.mcp_client import MCPClient
    client = MCPClient("uvx", ["mcp-server-time"])
    client.connect()
    tools = client.discover_tools()
    result = client.call_tool("get_current_time", {"timezone": "Asia/Shanghai"})
"""

import json
import subprocess
import os as _os
from typing import Any


# ── MCP 子进程环境白名单 ──
# MCP server 是可从 mcp_servers.json / REACT_AGENT_MCP_CONFIG 指定的第三方进程
# （例如 npx -y <任意包>），此前这里用 os.environ.copy() 把完整父环境（含
# DEEPSEEK_API_KEY 等全部密钥）交给它。改为与 harness/sandbox.py 同取向的白名单。
_MCP_ENV_ALLOWLIST = {
    # 进程启动必需
    "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "SYSTEMDRIVE",
    "TEMP", "TMP", "TMPDIR",
    # 运行库 / 证书
    "LANG", "LC_ALL", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS",
    # 包管理器缓存（uvx/npx 需要在可写位置落地）
    "HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
    "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME",
    "UV_CACHE_DIR", "PIP_CACHE_DIR", "npm_config_cache",
}
# 代理变量按前缀放行：代理本身常带 user:pass@，属凭据，需调用方显式开启
_MCP_PROXY_ENV_PREFIXES = ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY",
                           "http_proxy", "https_proxy", "no_proxy", "all_proxy")


class MCPRPCError(RuntimeError):
    """JSON-RPC error retaining the server's numeric code for Harness mapping."""

    def __init__(self, code: int | str, message: str, data: Any = None):
        self.code = code
        self.data = data
        super().__init__(f"MCP 错误 [{code}]: {message}")


def _mcp_child_env(extra: dict | None = None, *, allow_proxy: bool | None = None) -> dict:
    """构造 MCP 子进程环境；默认不继承宿主密钥与代理凭据。"""
    if allow_proxy is None:
        allow_proxy = _os.environ.get("REACT_AGENT_MCP_ALLOW_PROXY", "").strip().lower() in {
            "1", "true", "yes", "on",
        }
    env = {
        key: value
        for key, value in _os.environ.items()
        if key.upper() in _MCP_ENV_ALLOWLIST
        or key in _MCP_ENV_ALLOWLIST
    }
    if allow_proxy:
        env.update(
            {
                key: value
                for key, value in _os.environ.items()
                if key in _MCP_PROXY_ENV_PREFIXES
            }
        )
    env["PYTHONIOENCODING"] = "utf-8"
    if extra:
        env.update({str(k): str(v) for k, v in extra.items()})
    return env


class MCPClient:
    """通过 stdin/stdout（stdio）连接 MCP Server，实现 JSON-RPC 2.0 通信"""

    def __init__(self, command, args=None, env=None, *, retry_policy=None, idempotency_policy=None, idempotency_store=None):
        from react_agent.harness.runtime import IdempotencyPolicy, RetryPolicy

        self.command = command
        self.args = args or []
        self.env = env or {}
        self.proc = None
        self._req_id = 0
        self.tools = []
        self.specs = {}
        # Defaults preserve the historical single-attempt/no-cache behavior.
        self.retry_policy = retry_policy or RetryPolicy(max_attempts=1)
        self.idempotency_policy = idempotency_policy or IdempotencyPolicy("none")
        self._idempotency_results = idempotency_store if idempotency_store is not None else {}

    # ---------------------------------------------------------------
    # 生命周期
    # ---------------------------------------------------------------

    def connect(self, timeout=15):
        """启动 MCP Server 子进程 -> 握手 initialize"""
        env = _mcp_child_env(self.env)
        self.proc = subprocess.Popen(
            [self.command] + self.args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        resp = self._rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "mcp-client-py", "version": "1.0.0"},
        })
        si = resp.get("serverInfo", {})
        print(f"  [MCP] 已连接: {si.get('name', '?')} v{si.get('version', '?')}")
        self._notify("notifications/initialized")

    def close(self):
        """关闭连接，终止子进程"""
        if self.proc:
            try:
                self.proc.stdin.close()
            except Exception:
                pass
            self.proc.terminate()
            self.proc = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ---------------------------------------------------------------
    # MCP 方法
    # ---------------------------------------------------------------

    def discover_tools(self):
        """调用 tools/list -> 返回工具列表"""
        from react_agent.harness.tool_boundary import ToolSpec

        resp = self._rpc("tools/list")
        self.tools = resp.get("tools", [])
        self.specs = {
            spec.name: spec
            for spec in (ToolSpec.from_definition(item) for item in self.tools)
            if spec.name
        }
        for t in self.tools:
            desc = t.get("description", "")[:60]
            print(f"  [MCP] {t['name']} - {desc}")
        print(f"  [MCP] 共 {len(self.tools)} 个工具")
        return self.tools

    def call_tool(
        self,
        name,
        arguments=None,
        *,
        idempotency_key: str | None = None,
        call_id: str | None = None,
        timeout_seconds: float | None = None,
        max_output_chars: int | None = None,
    ):
        """调用 tools/call -> 返回纯文本结果"""
        from react_agent.harness.contracts import ToolCall, ToolCallError, ToolError
        from react_agent.harness.tool_boundary import (
            invoke_with_timeout,
            limit_tool_output,
            validate_tool_arguments,
        )
        from react_agent.harness.runtime import IdempotencyPolicy

        call = ToolCall(
            name=name,
            arguments=arguments or {},
            call_id=call_id,
            idempotency_key=idempotency_key,
            source="runtime",
        )
        tool_definition = next(
            (item for item in self.tools if item.get("name") == call.name), None
        )
        from react_agent.harness.tool_boundary import ToolSpec

        spec = self.specs.get(call.name)
        if spec is None and tool_definition is not None:
            spec = ToolSpec.from_definition(tool_definition)
        if spec is None:
            spec = ToolSpec(call.name)
        policy = self.idempotency_policy
        if spec.idempotency_level != "none":
            policy = type(policy)(
                mode=spec.idempotency_level,
                key_source=policy.key_source,
                replay_behavior=policy.replay_behavior,
                bind_payload=policy.bind_payload,
            )
        key, payload_hash, cached, replayed = policy.lookup(
            self._idempotency_results,
            call.name,
            call.arguments,
            key=call.idempotency_key,
            call_id=call.call_id,
        )
        if replayed:
            return cached

        if tool_definition:
            try:
                validate_tool_arguments(
                    json.loads(call.arguments), spec.parameters
                )
            except Exception as exc:
                raise ToolCallError(
                    ToolError.from_exception(exc, tool_name=call.name, source="mcp")
                ) from exc

        def operation() -> str:
            resp = self._rpc("tools/call", {
                "name": call.name,
                "arguments": json.loads(call.arguments),
            })
            texts = [c["text"] for c in resp.get("content", []) if c.get("type") == "text"]
            return "\n".join(texts)

        try:
            retry_policy = self.retry_policy
            if spec.retryable is False or (policy.mode == "none" and retry_policy.max_attempts > 1):
                retry_policy = retry_policy.with_max_attempts(1)
            result = retry_policy.run(
                lambda: invoke_with_timeout(
                    operation,
                    timeout_seconds if timeout_seconds is not None else spec.timeout_seconds,
                    tool_name=call.name,
                    source="mcp",
                )
            )
        except ToolCallError:
            raise
        except Exception as exc:
            raise ToolCallError(
                ToolError.from_exception(exc, tool_name=call.name, source="mcp")
            ) from exc
        result = limit_tool_output(
            result,
            max_output_chars if max_output_chars is not None else spec.max_output_chars,
        )
        policy.record(self._idempotency_results, key, payload_hash, result)
        return result

    def to_tool_definitions(self):
        """转成 OpenAI Function Calling JSON Schema"""
        defs = []
        for t in self.tools:
            spec = self.specs.get(t.get("name"))
            defs.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("inputSchema", {
                        "type": "object", "properties": {}
                    }),
                    **(
                        {
                            "timeout_seconds": spec.timeout_seconds,
                            "max_output_chars": spec.max_output_chars,
                            "idempotency_level": spec.idempotency_level,
                            "retryable": spec.retryable,
                        }
                        if spec is not None
                        else {}
                    ),
                },
            })
        return defs

    # ---------------------------------------------------------------
    # JSON-RPC 2.0 通信原语
    # ---------------------------------------------------------------

    def _rpc(self, method, params=None):
        self._req_id += 1
        req = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": self._req_id,
        }
        line = json.dumps(req) + "\n"
        self.proc.stdin.write(line.encode("utf-8"))
        self.proc.stdin.flush()

        resp_line = self.proc.stdout.readline()
        if not resp_line:
            raise RuntimeError("MCP Server 连接断开")
        resp_line = resp_line.decode("utf-8")
        resp = json.loads(resp_line)


        if "error" in resp:
            e = resp["error"]
            raise MCPRPCError(e.get("code", "unknown"), e.get("message", ""), e.get("data"))
        return resp.get("result", {})

    def _notify(self, method, params=None):
        req = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        line = json.dumps(req) + "\n"
        self.proc.stdin.write(line.encode("utf-8"))
        self.proc.stdin.flush()


class MockMCPClient:
    """离线 MCP 替身：不启子进程，接口与 MCPClient 对齐。

    开启方式：``REACT_AGENT_MCP_MOCK=1``（见 react_loop CLI / demo_mcp_mock.py）。
    用于 CI、面试 Demo、无 uvx 环境证明「工具协议合并」路径。
    """

    def __init__(self, command="mock", args=None, env=None, *, retry_policy=None, idempotency_policy=None, idempotency_store=None):
        from react_agent.harness.runtime import IdempotencyPolicy, RetryPolicy

        self.command = command
        self.args = args or []
        self.env = env or {}
        self.proc = None
        self.tools = []
        self._connected = False
        self.retry_policy = retry_policy or RetryPolicy(max_attempts=1)
        self.idempotency_policy = idempotency_policy or IdempotencyPolicy("none")
        self._idempotency_results = idempotency_store if idempotency_store is not None else {}
        self.specs = {}

    def connect(self, timeout=15):
        self._connected = True
        print("  [MCP] 已连接: mock-mcp-server v0.1.0 (REACT_AGENT_MCP_MOCK=1)")

    def close(self):
        self._connected = False
        self.proc = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def discover_tools(self):
        from react_agent.harness.tool_boundary import ToolSpec

        self.tools = [
            {
                "name": "get_current_time",
                "description": "Mock: return a fixed timezone timestamp",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "timezone": {"type": "string", "description": "IANA timezone"},
                    },
                },
            },
            {
                "name": "echo_note",
                "description": "Mock: echo a note back (protocol smoke)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                    },
                    "required": ["text"],
                },
            },
        ]
        self.specs = {
            spec.name: spec
            for spec in (ToolSpec.from_definition(item) for item in self.tools)
            if spec.name
        }
        for t in self.tools:
            print(f"  [MCP] {t['name']} - {t.get('description', '')[:60]}")
        print(f"  [MCP] 共 {len(self.tools)} 个工具（mock）")
        return self.tools

    def call_tool(
        self,
        name,
        arguments=None,
        *,
        idempotency_key: str | None = None,
        call_id: str | None = None,
        timeout_seconds: float | None = None,
        max_output_chars: int | None = None,
    ):
        from react_agent.harness.contracts import ToolCall, ToolCallError, ToolError
        from react_agent.harness.tool_boundary import (
            invoke_with_timeout,
            limit_tool_output,
            validate_tool_arguments,
        )
        from react_agent.harness.runtime import IdempotencyPolicy

        call = ToolCall(
            name=name,
            arguments=arguments or {},
            call_id=call_id,
            idempotency_key=idempotency_key,
            source="runtime",
        )
        tool_definition = next(
            (item for item in self.tools if item.get("name") == call.name), None
        )
        from react_agent.harness.tool_boundary import ToolSpec

        spec = self.specs.get(call.name)
        if spec is None and tool_definition is not None:
            spec = ToolSpec.from_definition(tool_definition)
        if spec is None:
            spec = ToolSpec(call.name)
        policy = self.idempotency_policy
        if spec.idempotency_level != "none":
            policy = type(policy)(
                mode=spec.idempotency_level,
                key_source=policy.key_source,
                replay_behavior=policy.replay_behavior,
                bind_payload=policy.bind_payload,
            )
        key, payload_hash, cached, replayed = policy.lookup(
            self._idempotency_results,
            call.name,
            call.arguments,
            key=call.idempotency_key,
            call_id=call.call_id,
        )
        if replayed:
            return cached

        canonical_arguments: dict[str, Any] = json.loads(call.arguments) or {}
        if tool_definition:
            try:
                validate_tool_arguments(
                    canonical_arguments, spec.parameters
                )
            except Exception as exc:
                raise ToolCallError(
                    ToolError.from_exception(exc, tool_name=call.name, source="mcp")
                ) from exc

        def operation() -> str:
            if call.name == "get_current_time":
                tz = canonical_arguments.get("timezone") or "Asia/Shanghai"
                return f"2026-07-19T09:00:00+08:00 ({tz}) [mock]"
            if call.name == "echo_note":
                return f"echo: {canonical_arguments.get('text', '')}"
            raise RuntimeError(f"MCP 错误 [-32601]: Unknown mock tool: {call.name}")

        try:
            retry_policy = self.retry_policy
            if spec.retryable is False or (policy.mode == "none" and retry_policy.max_attempts > 1):
                retry_policy = retry_policy.with_max_attempts(1)
            result = retry_policy.run(
                lambda: invoke_with_timeout(
                    operation,
                    timeout_seconds if timeout_seconds is not None else spec.timeout_seconds,
                    tool_name=call.name,
                    source="mcp",
                )
            )
        except ToolCallError:
            raise
        except Exception as exc:
            raise ToolCallError(
                ToolError.from_exception(exc, tool_name=call.name, source="mcp")
            ) from exc
        result = limit_tool_output(
            result,
            max_output_chars if max_output_chars is not None else spec.max_output_chars,
        )
        policy.record(self._idempotency_results, key, payload_hash, result)
        return result

    def to_tool_definitions(self):
        defs = []
        for t in self.tools:
            spec = self.specs.get(t.get("name"))
            defs.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("inputSchema", {
                        "type": "object", "properties": {}
                    }),
                    **(
                        {
                            "timeout_seconds": spec.timeout_seconds,
                            "max_output_chars": spec.max_output_chars,
                            "idempotency_level": spec.idempotency_level,
                            "retryable": spec.retryable,
                        }
                        if spec is not None
                        else {}
                    ),
                },
            })
        return defs


# ================================================================
# 命令行测试
# ================================================================
if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 2 and sys.argv[1] in ("--mock", "mock"):
        with MockMCPClient() as c:
            c.connect()
            c.discover_tools()
            print(c.call_tool("get_current_time", {"timezone": "UTC"}))
        sys.exit(0)
    if len(sys.argv) < 2:
        print("用法: python mcp_client.py uvx mcp-server-time")
        print("      python mcp_client.py --mock")
        sys.exit(1)
    with MCPClient(sys.argv[1], sys.argv[2:]) as c:
        c.connect()
        c.discover_tools()
