
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


class MCPClient:
    """通过 stdin/stdout（stdio）连接 MCP Server，实现 JSON-RPC 2.0 通信"""

    def __init__(self, command, args=None, env=None):
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.proc = None
        self._req_id = 0
        self.tools = []

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
        resp = self._rpc("tools/call", {
            "name": name,
            "arguments": arguments or {},
        })
        texts = [c["text"] for c in resp.get("content", []) if c.get("type") == "text"]
        return "\n".join(texts)

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
