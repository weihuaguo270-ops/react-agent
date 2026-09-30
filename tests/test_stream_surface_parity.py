"""两个服务面的 SSE 流式契约对等测试。

`/v1/chat/stream` 是同一份文档（`DEPLOY.md` 的事件表）承诺给客户端的接口，但
FastAPI 面此前只有一个「跑完再一次吐出终态」的精简版：没有 Runtime 进度事件、
没有心跳、没有取消语义，帧格式也与 stdlib 面不同。本文件同时验证：

1. 事件词表与顺序符合文档（started → …进度… → result/error → done）；
2. 帧格式（`id:` / `event:` / 多行 `data:`）**两个面完全一致**——用 stdlib 的真实
   SSE 端点与 FastAPI 的 ASGI 直连各跑一次，用同一个解析器比对；
3. 空闲发心跳、worker 异常与断连取消都转成事件而不是断流。
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import threading
import time

import pytest

httpx = pytest.importorskip("httpx")
pytest.importorskip("fastapi")

# 与 test_server_http.py 一致：让 stdlib 面的 /v1/chat 走离线 docs 路径（无 LLM）
os.environ.setdefault("REACT_AGENT_APP", "docs_troubleshoot")
os.environ.setdefault("REACT_AGENT_DEFAULT_APP", "docs_troubleshoot")
os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")
os.environ.setdefault("REACT_AGENT_DISABLE_MCP", "1")


def _parse_frames(text: str) -> list[dict]:
    """把 SSE 文本解析成 [{id, event, data}]（两个服务面共用同一个解析器）。

    按 SSE 规范实现：帧之间用空行分隔，帧内是若干 ``id:`` / ``event:`` /
    ``data:`` 行（多行 ``data:`` 用换行拼回）。
    """
    frames = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        if not block.strip():
            continue
        event_id = None
        event_name = None
        data_lines: list[str] = []
        for line in block.split("\n"):
            if line.startswith("id: "):
                event_id = int(line[len("id: "):])
            elif line.startswith("event: "):
                event_name = line[len("event: "):]
            elif line.startswith("data: "):
                data_lines.append(line[len("data: "):])
            else:
                raise AssertionError(f"帧里出现意外字段: {line!r}")
        if event_name is None:
            raise AssertionError(f"帧缺少 event 字段: {block!r}")
        frames.append(
            {"id": event_id, "event": event_name, "data": json.loads("\n".join(data_lines))}
        )
    return frames


class _FastapiStream:
    """ASGI 直连，可注入假 handler（不需要 uvicorn，也不碰真实 LLM）。"""

    def __init__(self, handler):
        from react_agent.server.fastapi_app import create_app

        self.api = create_app(chat_handler=handler, initialize_runtime=False)

    def stream_response(self, *, method="POST", body=None, params=None):
        async def go():
            transport = httpx.ASGITransport(app=self.api)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://127.0.0.1"
            ) as client:
                return await client.request(
                    method, "/v1/chat/stream", json=body, params=params
                )

        resp = asyncio.run(go())
        assert resp.status_code == 200, resp.text
        return resp

    def stream(self, **kwargs) -> str:
        return self.stream_response(**kwargs).text


class _StdlibStream:
    """真实 socket 上的 stdlib SSE 端点（离线 docs 路径，无 LLM）。"""

    def __init__(self):
        from http.server import ThreadingHTTPServer

        from react_agent.apps.docs_troubleshoot.index import reset_index
        from react_agent.server.app import AgentHandler
        from react_agent.tools import enable_app_tools

        enable_app_tools()
        reset_index()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), AgentHandler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.thread.join(timeout=5)

    def stream(self, *, query: str) -> tuple[dict, str]:
        raw = (
            f"GET /v1/chat/stream?{query} HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{self.port}\r\nConnection: close\r\n\r\n"
        ).encode()
        chunks: list[bytes] = []
        with socket.create_connection(("127.0.0.1", self.port), timeout=20) as sock:
            sock.sendall(raw)
            while True:
                data = sock.recv(65536)
                if not data:
                    break
                chunks.append(data)
        text = b"".join(chunks).decode("utf-8")
        head, _, body = text.partition("\r\n\r\n")
        lines = head.split("\r\n")
        assert " 200 " in lines[0], head
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                name, value = line.split(":", 1)
                headers[name.strip().lower()] = value.strip()
        return headers, body


# ── 1. 事件词表与顺序 ──


def _progress_handler(body, request_id):
    """模拟带 live 回调的运行时：先发进度事件，再返回带 agent_steps 的载荷。"""
    from react_agent.server.streaming import emit_event

    emit_event("runtime", {"status": "started", "mode": "test"})
    emit_event("tool_call", {"tool": "calculator", "arguments": {"expression": "1+1"}})
    emit_event("tool_result", {"tool": "calculator", "ok": True, "observation": "2"})
    return 200, {"answer": "2", "agent_steps": [{"thought": "算一下", "action": "calculator"}]}


def test_fastapi_stream_emits_documented_progress_vocabulary():
    frames = _parse_frames(_FastapiStream(_progress_handler).stream(body={"message": "1+1"}))

    assert [f["event"] for f in frames] == [
        "started",
        "runtime",
        "tool_call",
        "tool_result",
        "step",
        "result",
        "done",
    ]
    # 事件序号连续，客户端可据此对账
    assert [f["id"] for f in frames] == list(range(1, len(frames) + 1))
    # 每帧都带 request_id（便于跨日志关联）
    assert all(f["data"].get("request_id") for f in frames)
    assert frames[-1]["data"] == {"status": 200, "ok": True, "request_id": frames[0]["data"]["request_id"]}
    assert frames[5]["data"]["result"]["answer"] == "2"


def test_fastapi_stream_error_payload_uses_error_frame():
    def handler(body, request_id):
        return 422, {"error": {"code": "nope", "message": "bad"}}

    frames = _parse_frames(_FastapiStream(handler).stream(body={"message": "x"}))
    assert [f["event"] for f in frames] == ["started", "error", "done"]
    assert frames[1]["data"]["status"] == 422
    assert frames[2]["data"]["ok"] is False


# ── 2. 心跳与异常/取消语义 ──


def test_fastapi_stream_emits_heartbeat_while_idle(monkeypatch):
    monkeypatch.setattr("react_agent.server.streaming.HEARTBEAT_SECONDS", 0.05)

    def slow_handler(body, request_id):
        time.sleep(0.25)
        return 200, {"answer": "slow"}

    frames = _parse_frames(_FastapiStream(slow_handler).stream(body={"message": "slow"}))
    names = [f["event"] for f in frames]
    assert names[0] == "started" and names[-1] == "done"
    assert names.count("heartbeat") >= 2, names
    assert all("ts" in f["data"] for f in frames if f["event"] == "heartbeat")


def test_fastapi_stream_worker_exception_becomes_error_and_done():
    def handler(body, request_id):
        raise RuntimeError("boom")

    frames = _parse_frames(_FastapiStream(handler).stream(body={"message": "x"}))
    assert [f["event"] for f in frames] == ["started", "error", "done"]
    assert frames[1]["data"]["error"]["code"] == "internal_error"
    assert "boom" in frames[1]["data"]["error"]["message"]
    assert frames[2]["data"]["status"] == 500


def test_fastapi_stream_client_disconnect_emits_cancelled():
    from react_agent.llm import LLMCancelled

    def handler(body, request_id):
        raise LLMCancelled("client disconnected")

    frames = _parse_frames(_FastapiStream(handler).stream(body={"message": "x"}))
    assert [f["event"] for f in frames] == ["started", "cancelled", "done"]
    assert frames[1]["data"]["reason"] == "client_disconnected"
    assert frames[2]["data"]["cancelled"] is True
    assert frames[2]["data"]["status"] == 499


def test_client_disconnect_cancels_the_running_agent():
    """断开连接不只是停止推送：运行中的 Agent 必须被真正叫停。

    只停止推送的话，用户离开后 Agent 仍会跑完全部步数、空烧 LLM 调用——这是
    `streaming.request_cancel` 存在的唯一理由。这里消费第一帧后直接关掉生成器
    （等价于客户端断开），断言 worker 线程里的 Agent 观测到取消。
    """
    from react_agent.server.fastapi_app import _chat_event_stream

    observed: dict = {}

    def handler(body, request_id):
        from react_agent.server.streaming import is_cancelled

        deadline = time.time() + 5
        while time.time() < deadline:
            if is_cancelled():
                observed["cancelled"] = True
                return 200, {"answer": "stopped early"}
            time.sleep(0.02)
        return 200, {"answer": "never cancelled"}

    async def go():
        stream = _chat_event_stream(handler, {"message": "x"}, "req-cancel")
        first = await stream.__anext__()
        assert "event: started" in first
        await stream.aclose()  # 客户端断开
        for _ in range(250):
            if observed.get("cancelled"):
                return
            await asyncio.sleep(0.02)

    asyncio.run(go())
    assert observed.get("cancelled") is True


# ── 3. EventSource 的 GET 入口（查询参数 → 请求体） ──


def test_fastapi_stream_get_query_form_maps_body():
    seen: dict = {}

    def handler(body, request_id):
        seen.update(body)
        return 200, {"answer": "ok"}

    text = _FastapiStream(handler).stream(
        method="GET", params={"message": "hi", "app": "expense", "max_steps": "3"}
    )
    frames = _parse_frames(text)
    assert frames[0]["event"] == "started"
    assert seen["message"] == "hi"
    assert seen["app"] == "expense"
    assert seen["max_steps"] == 3  # 查询参数里的字符串被转成 int
    assert frames[-1]["event"] == "done"


# ── 4. 跨面帧格式一致（stdlib 真实端点 vs FastAPI ASGI） ──


def test_both_surfaces_produce_the_same_frame_format():
    stdlib = _StdlibStream()
    try:
        stdlib_headers, stdlib_body = stdlib.stream(
            query="message=%E7%BC%BA%E5%B0%91%20Authorization%20%E8%BF%94%E5%9B%9E%E4%BB%80%E4%B9%88"
        )
    finally:
        stdlib.close()
    stdlib_frames = _parse_frames(stdlib_body)

    fastapi_resp = _FastapiStream(
        lambda body, request_id: (200, {"answer": "ok"})
    ).stream_response(body={"message": "hi"})
    fastapi_frames = _parse_frames(fastapi_resp.text)

    # 同一个解析器能解析两边的帧，且都以 done 收尾、序号从 1 起连续
    for frames in (stdlib_frames, fastapi_frames):
        assert frames[0]["event"] == "started"
        assert frames[-1]["event"] == "done"
        assert [f["id"] for f in frames] == list(range(1, len(frames) + 1))
        assert all(isinstance(f["data"], dict) for f in frames)

    # 响应头也要一致：少了 X-Accel-Buffering: no，反代会把流缓冲住、流式变批式
    for headers in (stdlib_headers, dict(fastapi_resp.headers)):
        assert headers["content-type"].startswith("text/event-stream")
        assert "no-cache" in headers["cache-control"]
        assert headers["x-accel-buffering"] == "no"
        assert headers["connection"].lower() == "close"
        assert headers.get("x-request-id")

    # 帧文本形状一致：两边都由 streaming.sse_frame 产出
    from react_agent.server.streaming import sse_frame

    assert sse_frame("heartbeat", {"request_id": "r", "ts": 1.5}, "2") == (
        'id: 2\nevent: heartbeat\ndata: {"request_id":"r","ts":1.5}\n\n'
    )
    # 载荷里的换行不得截断帧（转义后仍是单帧往返）
    multiline = sse_frame("result", {"answer": "line1\nline2"}, "3")
    assert _parse_frames(multiline)[0]["data"]["answer"] == "line1\nline2"
