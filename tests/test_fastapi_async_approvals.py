"""FastAPI 服务面的异步人工审批链路（HITL over HTTP）回归测试。

stdlib 面早就把审批接在 HTTP 上；FastAPI 面（容器默认入口）此前既没有
``/v1/approvals``，也不设置请求级上下文，于是 ``DEPLOY.md`` 承诺的
「命中 CONFIRM → 返回 awaiting_approval → 人工经独立请求批准 → 带 approval_id
重试即放行」在默认入口上走不通。这里在 **HTTP 层**验证整条链路。

关键设计：假 handler 只调用**真实闸门**，且**不把 approval_id 写进 payload**
（真实轨迹里工具观测会被截断）。审批信号是 ContextVar——闸门写、响应侧读，
必须在同一个上下文里；一旦捕获跨了 ``run_in_threadpool`` 的边界就读不到，
响应不会带 approval_id，``capture_approval_status`` 的字符串兜底也无从下手，
测试立刻失败。
"""
from __future__ import annotations

import asyncio
import json
import time

import pytest

httpx = pytest.importorskip("httpx")
pytest.importorskip("fastapi")

TOKEN = "approval-test-token"


class _Client:
    """ASGI 直连（CI 的 ``[test]`` extra 不含 uvicorn）。"""

    def __init__(self, handler):
        from react_agent.server.fastapi_app import create_app

        self.api = create_app(chat_handler=handler, initialize_runtime=False)

    def request(self, method, path, *, json_body=None, headers=None):
        async def go():
            transport = httpx.ASGITransport(app=self.api)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://127.0.0.1"
            ) as client:
                return await client.request(method, path, headers=headers, json=json_body)

        return asyncio.run(go())


def _confirm_tool_handler(body, request_id):
    """模拟 Agent 命中 CONFIRM 级工具：过真实闸门，但不泄漏 approval_id。"""
    from react_agent.safety.permission_gate import permission_block_message

    blocked = permission_block_message("execute_python", {"code": "print(1)"})
    if blocked is None:
        return 200, {"answer": "工具已执行"}
    return 200, {"answer": "该操作需要人工批准，已登记待批项"}


@pytest.fixture
def approval_env(tmp_path, monkeypatch):
    """隔离待批项存储 + 打开异步审批模式。"""
    monkeypatch.setenv("REACT_AGENT_APPROVAL_DIR", str(tmp_path / "approvals"))
    monkeypatch.setenv("REACT_AGENT_APPROVAL_MODE", "async")
    monkeypatch.delenv("REACT_AGENT_STRICT_CONFIRM", raising=False)
    # 本机 shell 可能设了共享密钥，会让所有请求 401
    monkeypatch.delenv("REACT_AGENT_API_KEY", raising=False)
    monkeypatch.delenv("REACT_AGENT_AUTH_TOKEN", raising=False)
    from react_agent.safety import approvals
    from react_agent.safety.permission_gate import set_approval_credential, set_hitl

    set_hitl(None)
    set_approval_credential("")
    approvals.take_pending_approval()
    yield tmp_path / "approvals"
    set_approval_credential("")
    approvals.take_pending_approval()


def _first_approval(client, body=None) -> str:
    """触发一次需要审批的请求，返回其 approval_id。"""
    resp = client.request("POST", "/v1/chat", json_body=body or {"message": "清理日志"})
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload.get("status") == "awaiting_approval", payload
    approval_id = payload.get("approval_id")
    assert approval_id, payload
    return approval_id


# ── 1. 命中 CONFIRM：响应标注 awaiting_approval，并落盘待批项 ──


def test_chat_returns_awaiting_approval_and_lists_pending(approval_env):
    client = _Client(_confirm_tool_handler)
    approval_id = _first_approval(client)

    listed = client.request("GET", "/v1/approvals")
    assert listed.status_code == 200
    payload = listed.json()
    assert payload["mode"] == "async"
    pending = payload["pending"]
    assert [item["approval_id"] for item in pending] == [approval_id]
    assert pending[0]["tool"] == "execute_python"
    assert pending[0]["status"] == "pending"


# ── 2. 批准后带 approval_id 重试：放行；once 用掉即作废 ──


def test_approved_credential_lets_the_retry_through(approval_env):
    client = _Client(_confirm_tool_handler)
    approval_id = _first_approval(client)

    resolved = client.request(
        "POST", f"/v1/approvals/{approval_id}", json_body={"decision": "approve", "scope": "once"}
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["approval"]["status"] == "approved"

    retry = client.request(
        "POST", "/v1/chat", json_body={"message": "清理日志", "approval_id": approval_id}
    )
    assert retry.status_code == 200
    assert retry.json().get("answer") == "工具已执行"
    assert "approval_id" not in retry.json()

    # once 已消费：同一 approval_id 再用会被重新登记一个新的待批项
    again = client.request(
        "POST", "/v1/chat", json_body={"message": "清理日志", "approval_id": approval_id}
    )
    assert again.json().get("status") == "awaiting_approval"
    assert again.json().get("approval_id") != approval_id


def test_session_grant_allows_retry_without_credential(approval_env):
    client = _Client(_confirm_tool_handler)
    approval_id = _first_approval(client)

    resolved = client.request(
        "POST",
        f"/v1/approvals/{approval_id}",
        json_body={"decision": "approve", "scope": "session"},
    )
    assert resolved.status_code == 200

    retry = client.request("POST", "/v1/chat", json_body={"message": "再跑一次"})
    assert retry.json().get("answer") == "工具已执行"


# ── 3. 拒绝：仍然拦截，并重新登记待批项 ──


def test_denied_approval_keeps_blocking(approval_env):
    client = _Client(_confirm_tool_handler)
    approval_id = _first_approval(client)

    denied = client.request(
        "POST", f"/v1/approvals/{approval_id}", json_body={"decision": "deny"}
    )
    assert denied.status_code == 200
    assert denied.json()["approval"]["status"] == "denied"

    retry = client.request(
        "POST", "/v1/chat", json_body={"message": "清理日志", "approval_id": approval_id}
    )
    assert retry.json().get("status") == "awaiting_approval"
    assert retry.json().get("approval_id") != approval_id


# ── 4. 决议接口的错误映射（与 stdlib 面同一套码） ──


def test_resolve_error_mapping(approval_env):
    client = _Client(_confirm_tool_handler)

    missing = client.request("POST", "/v1/approvals/deadbeef", json_body={"decision": "approve"})
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "approval_not_found"

    approval_id = _first_approval(client)

    bad_decision = client.request(
        "POST", f"/v1/approvals/{approval_id}", json_body={"decision": "maybe"}
    )
    assert bad_decision.status_code == 409
    assert bad_decision.json()["error"]["code"] == "invalid_decision"

    bad_scope = client.request(
        "POST", f"/v1/approvals/{approval_id}", json_body={"decision": "approve", "scope": "forever"}
    )
    assert bad_scope.status_code == 409
    assert bad_scope.json()["error"]["code"] == "invalid_scope"

    assert client.request(
        "POST", f"/v1/approvals/{approval_id}", json_body={"decision": "approve"}
    ).status_code == 200
    # 已决议的待批项不能再决议一次
    double = client.request(
        "POST", f"/v1/approvals/{approval_id}", json_body={"decision": "approve"}
    )
    assert double.status_code == 409
    assert double.json()["error"]["code"] == "approval_not_pending"


# ── 5. /v1/tasks：worker 线程里执行，捕获同样要生效 ──


def test_task_submission_captures_approval_in_worker_thread(approval_env):
    """任务由 TaskManager 的 worker 线程跑：设置与捕获仍在同一次调用内。"""
    client = _Client(_confirm_tool_handler)
    submitted = client.request("POST", "/v1/tasks", json_body={"message": "清理日志"})
    assert submitted.status_code == 202, submitted.text
    task_id = submitted.json()["task_id"]

    deadline = time.time() + 10
    record = {}
    while time.time() < deadline:
        record = client.request("GET", f"/v1/tasks/{task_id}").json()
        if record.get("status") not in ("queued", "running"):
            break
        time.sleep(0.05)

    assert record.get("status") == "succeeded", record
    payload = record["result"]["payload"]
    assert payload["status"] == "awaiting_approval", payload
    assert payload["approval_id"]


# ── 6. SSE 通道发 approval_required 事件 ──

def test_stream_emits_approval_required(approval_env):
    client = _Client(_confirm_tool_handler)
    resp = client.request("POST", "/v1/chat/stream", json_body={"message": "清理日志"})
    assert resp.status_code == 200
    text = resp.text

    assert "event: approval_required" in text
    assert "event: done" in text
    # 审批事件先于终态事件（先告诉客户端要批什么，再给结果）
    assert text.index("event: approval_required") < text.index("event: done")

    data_line = text.split("event: approval_required\ndata: ", 1)[1].split("\n", 1)[0]
    approval_id = json.loads(data_line)["approval_id"]

    pending = client.request("GET", "/v1/approvals").json()["pending"]
    assert approval_id in [item["approval_id"] for item in pending]


# ── 7. 审批接口本身受共享密钥保护 ──

def test_approval_routes_are_authenticated(approval_env, monkeypatch):
    # 两个变量同时设置：本用例在「P0 之前」与「P0 之后」的代码上都成立
    monkeypatch.setenv("REACT_AGENT_API_KEY", TOKEN)
    monkeypatch.setenv("REACT_AGENT_AUTH_TOKEN", TOKEN)
    client = _Client(_confirm_tool_handler)

    assert client.request("GET", "/v1/approvals").status_code == 401
    assert client.request(
        "POST", "/v1/approvals/deadbeef", json_body={"decision": "approve"}
    ).status_code == 401

    ok = client.request("GET", "/v1/approvals", headers={"Authorization": f"Bearer {TOKEN}"})
    assert ok.status_code == 200
