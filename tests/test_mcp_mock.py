"""Mock MCP client — no subprocess / uvx."""
from __future__ import annotations

from react_agent.mcp_client import MockMCPClient


def test_mock_discover_and_call():
    c = MockMCPClient()
    c.connect()
    tools = c.discover_tools()
    names = {t["name"] for t in tools}
    assert "get_current_time" in names
    assert "echo_note" in names

    defs = c.to_tool_definitions()
    assert all(d["type"] == "function" for d in defs)

    out = c.call_tool("get_current_time", {"timezone": "UTC"})
    assert "mock" in out.lower() or "UTC" in out

    echoed = c.call_tool("echo_note", {"text": "hello"})
    assert "hello" in echoed
    c.close()


def test_mock_unknown_tool_raises():
    c = MockMCPClient()
    c.connect()
    c.discover_tools()
    try:
        c.call_tool("no_such_tool", {})
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "Unknown" in str(e) or "MCP" in str(e)
