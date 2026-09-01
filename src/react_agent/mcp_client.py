
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
import os as _os
import subprocess
import time
from urllib import error as _url_error
from urllib import request as _url_request


class MCPClient:
    """通过 stdin/stdout（stdio）连接 MCP Server，实现 JSON-RPC 2.0 通信"""

    def __init__(
        self,
        command,
        args=None,
        env=None,
        *,
        confirmation_fn=None,
        audit_hook=None,
        require_confirmation=False,
    ):
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.proc = None
        self._req_id = 0
        self.tools = []
        self.confirmation_fn = confirmation_fn
        self.audit_hook = audit_hook
        self.require_confirmation = require_confirmation
        self.audit_log = []

    # ---------------------------------------------------------------
    # 生命周期
    # ---------------------------------------------------------------

    def connect(self, timeout=15):
        """启动 MCP Server 子进程 -> 握手 initialize"""
        env = _os.environ.copy()
        env.update(self.env)
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
        resp = self._rpc("tools/list")
        self.tools = resp.get("tools", [])
        for t in self.tools:
            desc = t.get("description", "")[:60]
            print(f"  [MCP] {t['name']} - {desc}")
        print(f"  [MCP] 共 {len(self.tools)} 个工具")
        return self.tools

    def call_tool(self, name, arguments=None):
        """调用 tools/call -> 返回纯文本结果"""
        arguments = arguments or {}
        self._authorize(name, arguments)
        started = time.monotonic()
        self._audit("started", name, arguments)
        try:
            resp = self._rpc("tools/call", {
                "name": name,
                "arguments": arguments,
            })
        except Exception as exc:
            self._audit("failed", name, arguments, error=str(exc), duration_ms=_elapsed_ms(started))
            raise
        self._audit("completed", name, arguments, duration_ms=_elapsed_ms(started))
        texts = [c["text"] for c in resp.get("content", []) if c.get("type") == "text"]
        return "\n".join(texts)

    def _authorize(self, name, arguments):
        if not self.require_confirmation or not _is_high_risk_tool(self.tools, name):
            return
        if self.confirmation_fn is None or not self.confirmation_fn(name, arguments):
            raise PermissionError(f"MCP high-risk tool requires confirmation: {name}")

    def _audit(self, outcome, name, arguments, **extra):
        event = {
            "timestamp": time.time(),
            "transport": "stdio",
            "tool": name,
            "outcome": outcome,
            "arguments": _redact_arguments(arguments),
            **extra,
        }
        self.audit_log.append(event)
        if len(self.audit_log) > 1000:
            del self.audit_log[:-1000]
        if self.audit_hook is not None:
            self.audit_hook(dict(event))

    def to_tool_definitions(self):
        """转成 OpenAI Function Calling JSON Schema"""
        defs = []
        for t in self.tools:
            defs.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("inputSchema", {
                        "type": "object", "properties": {}
                    }),
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
            raise RuntimeError(f"MCP 错误 [{e.get('code')}]: {e.get('message')}")
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

    def __init__(self, command="mock", args=None, env=None):
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.proc = None
        self.tools = []
        self._connected = False
        self.audit_log = []

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
        for t in self.tools:
            print(f"  [MCP] {t['name']} - {t.get('description', '')[:60]}")
        print(f"  [MCP] 共 {len(self.tools)} 个工具（mock）")
        return self.tools

    def call_tool(self, name, arguments=None):
        arguments = arguments or {}
        if name == "get_current_time":
            tz = arguments.get("timezone") or "Asia/Shanghai"
            return f"2026-07-19T09:00:00+08:00 ({tz}) [mock]"
        if name == "echo_note":
            return f"echo: {arguments.get('text', '')}"
        raise RuntimeError(f"MCP 错误 [-32601]: Unknown mock tool: {name}")

    def to_tool_definitions(self):
        defs = []
        for t in self.tools:
            defs.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("inputSchema", {
                        "type": "object", "properties": {}
                    }),
                },
            })
        return defs


class StreamableHTTPMCPClient:
    """MCP client for remote Streamable HTTP endpoints.

    The endpoint may return either a normal JSON-RPC response or an SSE response
    containing JSON-RPC messages.  The implementation intentionally uses the
    standard library so the optional remote transport does not affect the core
    stdio/offline installation.
    """

    def __init__(
        self,
        url,
        *,
        token=None,
        token_env=None,
        headers=None,
        timeout=15,
        max_retries=2,
        retry_writes=False,
        confirmation_fn=None,
        audit_hook=None,
        require_confirmation=True,
    ):
        if not str(url).lower().startswith(("http://", "https://")):
            raise ValueError("remote MCP URL must use http:// or https://")
        self.url = str(url)
        self.token = token or (_os.environ.get(token_env, "") if token_env else "")
        self.headers = dict(headers or {})
        self.timeout = float(timeout)
        self.max_retries = max(0, int(max_retries))
        self.retry_writes = bool(retry_writes)
        self.confirmation_fn = confirmation_fn
        self.audit_hook = audit_hook
        self.require_confirmation = require_confirmation
        self._req_id = 0
        self.tools = []
        self.audit_log = []
        self.session_id = None

    def connect(self, timeout=None):
        self._rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "react-agent-http-mcp", "version": "1.0.0"},
        }, timeout=timeout)
        self._notify("notifications/initialized")

    def close(self):
        self.session_id = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def discover_tools(self):
        resp = self._rpc("tools/list")
        self.tools = resp.get("tools", [])
        return self.tools

    def call_tool(self, name, arguments=None):
        arguments = arguments or {}
        high_risk = _is_high_risk_tool(self.tools, name)
        if self.require_confirmation and high_risk:
            if self.confirmation_fn is None or not self.confirmation_fn(name, arguments):
                self._audit("blocked", name, arguments, error="confirmation_required")
                raise PermissionError(f"MCP high-risk tool requires confirmation: {name}")
        started = time.monotonic()
        self._audit("started", name, arguments)
        try:
            resp = self._rpc(
                "tools/call",
                {"name": name, "arguments": arguments},
                retryable=self.retry_writes or not high_risk,
            )
        except Exception as exc:
            self._audit("failed", name, arguments, error=str(exc), duration_ms=_elapsed_ms(started))
            raise
        self._audit("completed", name, arguments, duration_ms=_elapsed_ms(started))
        texts = [c["text"] for c in resp.get("content", []) if c.get("type") == "text"]
        return "\n".join(texts)

    def to_tool_definitions(self):
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("inputSchema", {"type": "object", "properties": {}}),
                },
            }
            for t in self.tools
        ]

    def _rpc(self, method, params=None, *, timeout=None, retryable=True):
        self._req_id += 1
        request_id = self._req_id
        payload = json.dumps({
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": request_id,
        }).encode("utf-8")
        attempts = self.max_retries + 1 if retryable else 1
        last_error = None
        for attempt in range(attempts):
            try:
                response = self._post(payload, timeout=timeout)
                if "error" in response:
                    error = response["error"]
                    raise RuntimeError(f"MCP 错误 [{error.get('code')}]: {error.get('message')}")
                return response.get("result", {})
            except Exception as exc:
                last_error = exc
                if attempt + 1 >= attempts or not _is_retryable_error(exc):
                    raise
                time.sleep(min(2.0, 0.25 * (2 ** attempt)))
        raise last_error or RuntimeError("remote MCP request failed")

    def _post(self, payload, *, timeout=None, expect_response=True):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **self.headers,
        }
        if self.token:
            headers.setdefault("Authorization", f"Bearer {self.token}")
        if self.session_id:
            headers.setdefault("Mcp-Session-Id", self.session_id)
        request = _url_request.Request(self.url, data=payload, headers=headers, method="POST")
        try:
            with _url_request.urlopen(request, timeout=timeout or self.timeout) as response:
                session_id = response.headers.get("Mcp-Session-Id")
                if session_id:
                    self.session_id = session_id
                content_type = response.headers.get("Content-Type", "").lower()
                if "text/event-stream" in content_type:
                    return _read_sse_jsonrpc(response)
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else ({} if not expect_response else {})
        except _url_error.HTTPError as exc:
            if exc.code in {408, 429} or exc.code >= 500:
                raise _RetryableHTTPError(f"MCP HTTP {exc.code}") from exc
            raise
        except (_url_error.URLError, TimeoutError) as exc:
            raise _RetryableHTTPError(str(exc)) from exc

    def _notify(self, method, params=None):
        self._req_id += 1
        payload = json.dumps({
            "jsonrpc": "2.0", "method": method, "params": params or {}
        }).encode("utf-8")
        self._post(payload, expect_response=False)

    def _audit(self, outcome, name, arguments, **extra):
        event = {
            "timestamp": time.time(),
            "transport": "streamable_http",
            "server": self.url,
            "tool": name,
            "outcome": outcome,
            "arguments": _redact_arguments(arguments),
            **extra,
        }
        self.audit_log.append(event)
        if len(self.audit_log) > 1000:
            del self.audit_log[:-1000]
        if self.audit_hook is not None:
            self.audit_hook(dict(event))


class _RetryableHTTPError(RuntimeError):
    pass


def _read_sse_jsonrpc(response):
    data_lines = []
    for raw_line in response:
        line = raw_line.decode("utf-8").rstrip("\r\n")
        if not line:
            if data_lines:
                message = json.loads("\n".join(data_lines))
                if "id" in message or "result" in message or "error" in message:
                    return message
                data_lines = []
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if data_lines:
        return json.loads("\n".join(data_lines))
    raise RuntimeError("MCP SSE stream ended without a JSON-RPC response")


def _is_retryable_error(exc):
    return isinstance(exc, (_RetryableHTTPError, TimeoutError, _url_error.URLError))


def _elapsed_ms(started):
    return round((time.monotonic() - started) * 1000, 3)


def _redact_arguments(arguments):
    sensitive = {"authorization", "password", "secret", "token", "api_key", "apikey"}
    def redact(value, key=None):
        if key is not None and key.lower() in sensitive:
            return "<REDACTED>"
        if isinstance(value, dict):
            return {str(k): redact(v, str(k)) for k, v in value.items()}
        if isinstance(value, list):
            return [redact(item) for item in value]
        if isinstance(value, tuple):
            return [redact(item) for item in value]
        return value

    return redact(arguments or {})


def _is_high_risk_tool(tools, name):
    metadata = next((tool for tool in tools if tool.get("name") == name), {})
    annotations = metadata.get("annotations") or {}
    if annotations.get("readOnlyHint") is True:
        return False
    if annotations.get("destructiveHint") is True or annotations.get("idempotentHint") is False:
        return True
    lowered = str(name).lower()
    return lowered.startswith(("write", "create", "update", "delete", "remove", "send", "merge", "deploy", "execute"))


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
