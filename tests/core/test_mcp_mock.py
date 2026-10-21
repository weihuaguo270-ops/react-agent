"""Mock MCP client — no subprocess / uvx."""
from __future__ import annotations

import pytest

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
        assert getattr(e, "error", None) is not None
        assert e.error.to_dict()["error_code"] == "tool_not_found"


def test_mock_call_uses_tool_call_argument_normalization():
    c = MockMCPClient()
    c.connect()
    c.discover_tools()
    assert "hello" in c.call_tool("echo_note", {"text": "hello"})
    with pytest.raises(ValueError, match="valid JSON"):
        c.call_tool("echo_note", "not-json")


def test_mock_call_replays_same_idempotency_key_and_rejects_payload_conflict():
    from react_agent.harness import IdempotencyPolicy

    c = MockMCPClient(idempotency_policy=IdempotencyPolicy("required"))
    first = c.call_tool("echo_note", {"text": "hello"}, idempotency_key="mcp-1")
    assert c.call_tool("echo_note", {"text": "hello"}, idempotency_key="mcp-1") == first
    with pytest.raises(ValueError, match="idempotency key conflicts"):
        c.call_tool("echo_note", {"text": "changed"}, idempotency_key="mcp-1")


def test_mock_call_requires_key_when_policy_is_required():
    from react_agent.harness import IdempotencyPolicy

    c = MockMCPClient(idempotency_policy=IdempotencyPolicy("required"))
    with pytest.raises(ValueError, match="idempotency key is required"):
        c.call_tool("echo_note", {"text": "hello"})


def test_stdio_client_uses_shared_retry_policy_for_tool_calls(monkeypatch):
    from react_agent.harness import RetryPolicy
    from react_agent.mcp_client import MCPClient

    client = MCPClient("unused", retry_policy=RetryPolicy(max_attempts=2, base_delay=0, jitter_ratio=0))
    attempts = []

    def rpc(_method, _params):
        attempts.append(1)
        if len(attempts) == 1:
            raise TimeoutError("MCP timeout")
        return {"content": [{"type": "text", "text": "ok"}]}

    monkeypatch.setattr(client, "_rpc", rpc)
    assert client.call_tool("echo_note", {"text": "hello"}) == "ok"
    assert len(attempts) == 2

