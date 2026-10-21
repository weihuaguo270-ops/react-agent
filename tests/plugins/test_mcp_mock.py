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
        assert e.error.to_dict()["error_code"] == "tool_not_found"


def test_mock_tool_schema_failure_uses_shared_error_contract():
    from react_agent.harness.contracts import ToolCallError

    c = MockMCPClient()
    c.connect()
    c.discover_tools()
    try:
        c.call_tool("echo_note", {"text": 123})
        assert False, "expected typed tool error"
    except ToolCallError as exc:
        payload = exc.error.to_dict()
        assert payload["error_code"] == "invalid_arguments"
        assert payload["stop_reason"] == "parse_error"


def test_mock_mcp_can_use_durable_idempotency_store(tmp_path):
    from react_agent.harness import IdempotencyPolicy, JsonIdempotencyStore

    store_path = tmp_path / "mcp-idempotency.json"
    first = MockMCPClient(
        idempotency_policy=IdempotencyPolicy("required"),
        idempotency_store=JsonIdempotencyStore(store_path),
    )
    first.connect()
    first.discover_tools()
    assert "hello" in first.call_tool("echo_note", {"text": "hello"}, idempotency_key="mcp-1")
    first.close()

    second = MockMCPClient(
        idempotency_policy=IdempotencyPolicy("required"),
        idempotency_store=JsonIdempotencyStore(store_path),
    )
    second.connect()
    second.discover_tools()
    assert "hello" in second.call_tool("echo_note", {"text": "hello"}, idempotency_key="mcp-1")
    second.close()
