"""Offline contract tests for the remote MCP Streamable HTTP client."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


class _MCPHandler(BaseHTTPRequestHandler):
    calls = 0
    auth_values = []

    def log_message(self, *_args):
        return

    def do_POST(self):
        _MCPHandler.auth_values.append(self.headers.get("Authorization"))
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        method = body.get("method")
        if method == "notifications/initialized":
            self.send_response(202)
            self.end_headers()
            return
        if method == "initialize":
            self._json({"jsonrpc": "2.0", "id": body["id"], "result": {}})
            return
        if method == "tools/list":
            self._json({
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {"tools": [
                    {"name": "search", "inputSchema": {"type": "object"},
                     "annotations": {"readOnlyHint": True}},
                    {"name": "deploy", "inputSchema": {"type": "object"},
                     "annotations": {"destructiveHint": True}},
                ]},
            })
            return
        if method == "tools/call":
            _MCPHandler.calls += 1
            if _MCPHandler.calls == 1:
                self.send_response(503)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            message = {"jsonrpc": "2.0", "id": body["id"], "result": {
                "content": [{"type": "text", "text": "remote-ok"}]
            }}
            self.wfile.write(f"event: message\ndata: {json.dumps(message)}\n\n".encode())
            return
        self.send_response(404)
        self.end_headers()

    def _json(self, payload):
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Mcp-Session-Id", "test-session")
        self.end_headers()
        self.wfile.write(raw)


@pytest.fixture
def mcp_server():
    _MCPHandler.calls = 0
    _MCPHandler.auth_values = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MCPHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/mcp"
    finally:
        server.shutdown()
        server.server_close()


def test_remote_mcp_json_sse_retry_auth_and_audit(mcp_server):
    from react_agent.mcp_client import StreamableHTTPMCPClient

    client = StreamableHTTPMCPClient(
        mcp_server, token="test-token", max_retries=1
    )
    client.connect()
    tools = client.discover_tools()
    assert {tool["name"] for tool in tools} == {"search", "deploy"}
    assert client.call_tool(
        "search", {"query": "mcp", "credentials": {"token": "secret-value"}}
    ) == "remote-ok"
    assert _MCPHandler.calls == 2
    assert _MCPHandler.auth_values
    assert all(value == "Bearer test-token" for value in _MCPHandler.auth_values)
    assert [event["outcome"] for event in client.audit_log] == [
        "started", "completed"
    ]
    assert (
        client.audit_log[0]["arguments"]["credentials"]["token"]
        == "<REDACTED>"
    )


def test_remote_mcp_high_risk_requires_confirmation(mcp_server):
    from react_agent.mcp_client import StreamableHTTPMCPClient

    client = StreamableHTTPMCPClient(mcp_server)
    client.connect()
    client.discover_tools()
    with pytest.raises(PermissionError):
        client.call_tool("deploy", {})
    assert client.audit_log[-1]["outcome"] == "blocked"

    approved = StreamableHTTPMCPClient(
        mcp_server,
        confirmation_fn=lambda _name, _args: True,
        retry_writes=True,
    )
    approved.connect()
    approved.discover_tools()
    # The first call receives the fixture's transient 503 and is retried.
    assert approved.call_tool("deploy", {}) == "remote-ok"
