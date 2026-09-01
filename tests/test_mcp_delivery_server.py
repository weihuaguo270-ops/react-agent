"""Contract tests for the remote GitHub/CI MCP service policy."""
from __future__ import annotations

import json

def _call(service, method, params=None, *, auth="Bearer server-token", request_id=1):
    return service.handle(
        {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}},
        authorization=auth,
    )


def test_server_auth_tools_and_write_policy():
    from react_agent.server.mcp_delivery import MCPDeliveryService

    service = MCPDeliveryService(token="server-token")
    unauthorized = _call(service, "tools/list", auth="Bearer wrong")
    assert unauthorized["error"]["code"] == -32001

    listed = _call(service, "tools/list")
    names = {tool["name"] for tool in listed["result"]["tools"]}
    assert {"create_draft_pr", "get_ci_status", "trigger_ci"} <= names

    blocked = _call(
        service,
        "tools/call",
        {"name": "create_draft_pr", "arguments": {
            "repository": "https://github.com/example/repo",
            "base_branch": "main",
            "branch": "agent/task-1",
            "task_id": "task-1",
            "diff": "diff --git a/a b/a",
            "plan_sha256": "abc",
            "idempotency_key": "key-1",
            "allow_external_write": False,
        }},
    )
    assert blocked["error"]["code"] == -32602
    assert "approval" in blocked["error"]["message"]


def test_server_approved_write_is_idempotent_and_ci_read_write_split():
    from react_agent.server.mcp_delivery import MCPDeliveryService

    service = MCPDeliveryService(token="server-token")
    arguments = {
        "repository": "https://github.com/example/repo",
        "base_branch": "main",
        "branch": "agent/task-1",
        "task_id": "task-1",
        "issue_url": "https://github.com/example/repo/issues/1",
        "diff": "diff --git a/a b/a",
        "plan_sha256": "abc",
        "idempotency_key": "key-1",
        "approver": "reviewer@example.com",
        "approved_at": "2026-08-30T00:00:00Z",
        "allow_external_write": True,
    }
    first = _call(service, "tools/call", {"name": "create_draft_pr", "arguments": arguments})
    second = _call(service, "tools/call", {"name": "create_draft_pr", "arguments": arguments})
    first_payload = json.loads(first["result"]["content"][0]["text"])
    second_payload = json.loads(second["result"]["content"][0]["text"])
    assert first_payload["url"] == second_payload["url"]
    assert second_payload["idempotent_replay"] is True

    status = _call(
        service,
        "tools/call",
        {"name": "get_ci_status", "arguments": {
            "repository": arguments["repository"], "ref": "main"
        }},
    )
    assert status["result"]["content"]

    trigger = dict(arguments, ref="agent/task-1", workflow="tests")
    trigger_result = _call(
        service,
        "tools/call",
        {"name": "trigger_ci", "arguments": trigger},
    )
    assert trigger_result["result"]["content"]
