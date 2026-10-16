"""End-to-end MCP stdio contract tests against a real child process."""
from __future__ import annotations

import json
import sys
import textwrap

import pytest

from react_agent.mcp_client import MCPClient


SERVER = textwrap.dedent(
    r'''
    import json, sys, time

    TOOLS = [
        {
            "name": "echo",
            "description": "echo a text",
            "inputSchema": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
                "additionalProperties": False,
            },
            "timeout_seconds": 0.2,
            "max_output_chars": 8,
            "idempotency_level": "required",
        },
        {
            "name": "slow",
            "description": "sleep before replying",
            "inputSchema": {"type": "object", "properties": {}},
            "timeout_seconds": 0.01,
            "max_output_chars": 128,
        },
    ]

    def reply(request, result=None, error=None):
        payload = {"jsonrpc": "2.0", "id": request["id"]}
        if error is not None:
            payload["error"] = error
        else:
            payload["result"] = result or {}
        sys.stdout.write(json.dumps(payload) + "\n")
        sys.stdout.flush()

    for line in sys.stdin:
        request = json.loads(line)
        if "id" not in request:
            continue
        method = request.get("method")
        if method == "initialize":
            reply(request, {"serverInfo": {"name": "contract-fixture", "version": "1"}})
        elif method == "tools/list":
            reply(request, {"tools": TOOLS})
        elif method == "tools/call":
            name = request.get("params", {}).get("name")
            args = request.get("params", {}).get("arguments", {})
            if name == "echo":
                reply(request, {"content": [{"type": "text", "text": "echo:" + args["text"]}]})
            elif name == "slow":
                time.sleep(0.2)
                reply(request, {"content": [{"type": "text", "text": "late"}]})
            else:
                reply(request, error={"code": -32601, "message": "method not found"})
    ''',
)


def client() -> MCPClient:
    return MCPClient(sys.executable, ["-u", "-c", SERVER])


def test_real_mcp_stdio_uses_tool_spec_and_shared_errors():
    from react_agent.harness.contracts import ToolCallError

    c = client()
    c.connect()
    try:
        c.discover_tools()
        assert c.specs["echo"].timeout_seconds == 0.2
        assert c.specs["echo"].max_output_chars == 8
        assert c.specs["echo"].idempotency_level == "required"

        with pytest.raises(ValueError, match="idempotency key is required"):
            c.call_tool("echo", {"text": "x"})
        output = c.call_tool("echo", {"text": "abcdefghijk"}, idempotency_key="k1")
        assert output.startswith("echo:ab")
        replay = c.call_tool("echo", {"text": "abcdefghijk"}, idempotency_key="k1")
        assert replay.startswith("echo:ab")

        with pytest.raises(ToolCallError) as bad_args:
            c.call_tool("echo", {"text": 3}, idempotency_key="bad")
        assert bad_args.value.error.to_dict()["error_code"] == "invalid_arguments"

        with pytest.raises(ToolCallError) as missing:
            c.call_tool("no_such_tool", {})
        assert missing.value.error.to_dict()["error_code"] == "tool_not_found"

        with pytest.raises(ToolCallError) as timed_out:
            c.call_tool("slow", {})
        timeout_payload = timed_out.value.error.to_dict()
        assert timeout_payload["error_code"] == "timeout"
        assert timeout_payload["stop_reason"] == "timeout"
    finally:
        c.close()
