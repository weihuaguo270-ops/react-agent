"""流式 LLM 与答案增量投递的回归测试。

覆盖通道 3（LLM 流式）与通道 1（SSE 答案增量 + 断连取消）：

1. OpenAI 兼容 SSE 增量解析（正文分片、[DONE]、空行）
2. tool_calls 跨 chunk 分片合并
3. 取消：回调抛 ``LLMCancelled`` 立即中止读取并向上传播
4. react_loop 把增量转成 ``answer_delta`` 事件、结束时发 ``answer``
5. 步间取消：客户端断开后不再发起后续 LLM 调用
6. HTTP 端到端：真实 SSE 连接断开应真正停掉 Agent（而非只停止推送）
"""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# RAG 索引加载是重操作，且与本文件要验证的传输行为无关
os.environ["REACT_AGENT_SKIP_RAG"] = "1"
os.environ.setdefault("REACT_AGENT_TOOL_GUARD", "0")
os.environ.setdefault("REACT_AGENT_SELF_REPAIR", "0")

import react_agent.llm as llm_module  # noqa: E402


# ── 假 LLM 服务端：按 OpenAI 兼容格式吐 SSE ──


class _FakeLLMHandler(BaseHTTPRequestHandler):
    # 由测试注入：list[dict] 每个元素是一条 chunk 的 delta
    deltas: list = []
    status: int = 200
    delay: float = 0.0

    def log_message(self, *args):  # 静音
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        if self.status != 200:
            body = json.dumps({"error": {"message": "boom"}}).encode()
            self.send_response(self.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for delta in type(self).deltas:
            if type(self).delay:
                time.sleep(type(self).delay)
            chunk = {"choices": [{"index": 0, "delta": delta}]}
            try:
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
        try:
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return


@pytest.fixture
def fake_llm(monkeypatch):
    """启动假 LLM 服务端并让 ``LLM(provider='custom')`` 指向它。"""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeLLMHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("LLM_BASE_URL", f"http://127.0.0.1:{server.server_address[1]}")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setattr(llm_module, "_CONFIG", None)
    _FakeLLMHandler.status = 200
    _FakeLLMHandler.delay = 0.0
    try:
        yield _FakeLLMHandler
    finally:
        server.shutdown()
        thread.join(timeout=5)
        llm_module._CONFIG = None


def _llm():
    return llm_module.LLM(provider="custom")


# ── 1/2. SSE 解析 ──


def test_stream_collects_content_deltas(fake_llm):
    fake_llm.deltas = [
        {"content": "你好"},
        {"content": "，世界"},
        {"content": "！"},
    ]
    seen: list[str] = []
    msg = _llm().chat([{"role": "user", "content": "hi"}], on_delta=seen.append)
    assert seen == ["你好", "，世界", "！"]
    assert msg["content"] == "你好，世界！"
    assert msg["role"] == "assistant"
    assert "tool_calls" not in msg


def test_stream_ignores_empty_and_non_data_lines(fake_llm):
    fake_llm.deltas = [{"content": "A"}, {}, {"content": "B"}]
    seen: list[str] = []
    msg = _llm().chat([{"role": "user", "content": "hi"}], on_delta=seen.append)
    assert seen == ["A", "B"]
    assert msg["content"] == "AB"


def test_stream_merges_tool_call_fragments(fake_llm):
    fake_llm.deltas = [
        {"tool_calls": [{"index": 0, "id": "call_1",
                         "function": {"name": "calculator", "arguments": '{"expr'}}]},
        {"tool_calls": [{"index": 0, "function": {"arguments": 'ession": "1+1"}'}}]},
    ]
    msg = _llm().chat([{"role": "user", "content": "hi"}], on_delta=lambda _s: None)
    assert msg["tool_calls"][0]["id"] == "call_1"
    assert msg["tool_calls"][0]["function"]["name"] == "calculator"
    assert msg["tool_calls"][0]["function"]["arguments"] == '{"expression": "1+1"}'


def test_stream_merges_multiple_tool_calls_by_index(fake_llm):
    fake_llm.deltas = [
        {"tool_calls": [{"index": 0, "id": "a", "function": {"name": "t1", "arguments": "{}"}}]},
        {"tool_calls": [{"index": 1, "id": "b", "function": {"name": "t2", "arguments": "{}"}}]},
    ]
    msg = _llm().chat([{"role": "user", "content": "hi"}], on_delta=lambda _s: None)
    assert [tc["function"]["name"] for tc in msg["tool_calls"]] == ["t1", "t2"]


def test_stream_sets_stream_flag_in_payload(fake_llm):
    captured: dict = {}
    original = llm_module.LLM.build_payload

    def spy(self, *args, **kwargs):
        payload = original(self, *args, **kwargs)
        captured["payload"] = payload
        return payload

    fake_llm.deltas = [{"content": "x"}]
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(llm_module.LLM, "build_payload", spy)
        _llm().chat([{"role": "user", "content": "hi"}], on_delta=lambda _s: None)
    assert captured["payload"]["stream"] is True


def test_non_stream_path_unchanged(fake_llm):
    """不传 on_delta 时不带 stream 标记（保持既有一次性返回行为）。"""
    captured: dict = {}
    original = llm_module.LLM.build_payload

    def spy(self, *args, **kwargs):
        payload = original(self, *args, **kwargs)
        captured["payload"] = payload
        return payload

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(llm_module.LLM, "build_payload", spy)
        # 假服务端只吐 SSE；非流式解析会失败并返回错误文案，但不该带 stream
        msg = _llm().chat([{"role": "user", "content": "hi"}])
    assert "stream" not in captured["payload"]
    assert "content" in msg


def test_stream_http_error_becomes_message(fake_llm):
    fake_llm.status = 500
    msg = _llm().chat([{"role": "user", "content": "hi"}], on_delta=lambda _s: None)
    assert "LLM调用失败" in msg["content"]


# ── 3. 取消传播 ──


def test_callback_exception_aborts_stream(fake_llm):
    from react_agent.llm import LLMCancelled

    fake_llm.deltas = [{"content": "A"}, {"content": "B"}, {"content": "C"}]
    seen: list[str] = []

    def stopper(piece: str):
        seen.append(piece)
        raise LLMCancelled("stop now")

    with pytest.raises(LLMCancelled):
        _llm().chat([{"role": "user", "content": "hi"}], on_delta=stopper)
    # 第一段之后即中止，不应读完
    assert seen == ["A"]


def test_llmcancelled_is_not_a_urlerror():
    """取消必须与网络错误区分开，否则会被误当失败重试/上报。"""
    from react_agent.llm import LLMCancelled

    assert not issubclass(LLMCancelled, urllib.error.URLError)
    assert not issubclass(LLMCancelled, urllib.error.HTTPError)


# ── 4. react_loop 集成：增量 → answer_delta / answer 事件 ──


class _ScriptedLLM:
    """按脚本逐步返回消息；可观测被调用次数。"""

    def __init__(self, script, delta_cb=None):
        self.model = "scripted"
        self.api_key = "x"
        self.provider_name = "scripted"
        self.script = list(script)
        self.calls = 0
        self.received_on_delta = []

    def chat(self, messages, tool_defs=None, temperature=None,
             max_tokens=None, max_retries=2, on_delta=None):
        self.calls += 1
        msg = self.script[min(self.calls - 1, len(self.script) - 1)]
        self.received_on_delta.append(on_delta)
        if on_delta and msg.get("content"):
            for piece in str(msg["content"]):
                on_delta(piece)
        return msg


@pytest.fixture
def event_sink():
    """安装事件收集器 + 取消事件，返回 (events, cancel)。"""
    from react_agent.server import streaming

    events: list[tuple[str, dict]] = []
    tokens, cancel_event = streaming.install(lambda e, d: events.append((e, d)))
    try:
        # 显式传入 event：与生产路径一致，不依赖 ContextVar 跨线程传播
        yield events, lambda: streaming.request_cancel(cancel_event)
    finally:
        streaming.reset(tokens)


def test_react_loop_emits_answer_delta_and_answer(monkeypatch, event_sink):
    events, _cancel = event_sink
    from react_agent import react_loop as rl

    scripted = _ScriptedLLM([{"role": "assistant", "content": "FINAL ANSWER: 42"}])
    monkeypatch.setattr(rl, "_active_llm", lambda: scripted)
    monkeypatch.setattr(rl, "start_trajectory", lambda *a, **k: None)
    monkeypatch.setattr(rl, "_finish_with_save", lambda *a, **k: None)
    monkeypatch.setattr(rl, "current_trajectory", lambda: None)
    monkeypatch.setenv("REACT_AGENT_LLM_STREAM", "1")

    answer = rl.react_loop("q", max_steps=1)

    names = [e for e, _ in events]
    assert "answer_delta" in names, names
    assert "answer" in names, names
    deltas = "".join(d["delta"] for e, d in events if e == "answer_delta")
    assert "FINAL ANSWER: 42" in deltas
    answer_evt = next(d for e, d in events if e == "answer")
    assert answer_evt["answer"] == "42"
    assert answer == "42"


def test_react_loop_passes_on_delta_when_streaming_enabled(monkeypatch, event_sink):
    from react_agent import react_loop as rl

    scripted = _ScriptedLLM([{"role": "assistant", "content": "FINAL ANSWER: x"}])
    monkeypatch.setattr(rl, "_active_llm", lambda: scripted)
    monkeypatch.setattr(rl, "start_trajectory", lambda *a, **k: None)
    monkeypatch.setattr(rl, "_finish_with_save", lambda *a, **k: None)
    monkeypatch.setattr(rl, "current_trajectory", lambda: None)
    monkeypatch.setenv("REACT_AGENT_LLM_STREAM", "1")

    rl.react_loop("q", max_steps=1)
    assert scripted.received_on_delta[0] is not None


def test_react_loop_skips_on_delta_when_streaming_disabled(monkeypatch, event_sink):
    from react_agent import react_loop as rl

    scripted = _ScriptedLLM([{"role": "assistant", "content": "FINAL ANSWER: x"}])
    monkeypatch.setattr(rl, "_active_llm", lambda: scripted)
    monkeypatch.setattr(rl, "start_trajectory", lambda *a, **k: None)
    monkeypatch.setattr(rl, "_finish_with_save", lambda *a, **k: None)
    monkeypatch.setattr(rl, "current_trajectory", lambda: None)
    monkeypatch.setenv("REACT_AGENT_LLM_STREAM", "0")

    rl.react_loop("q", max_steps=1)
    assert scripted.received_on_delta[0] is None


# ── 5. 步间取消：断开后不再发起 LLM 调用 ──


def test_react_loop_stops_after_cancel(monkeypatch, event_sink):
    """步间检测到取消：不再调用 LLM，抛 LLMCancelled 终止循环。"""
    _events, cancel = event_sink
    from react_agent import react_loop as rl
    from react_agent.llm import LLMCancelled

    # 每步都要求调工具，模拟多步循环
    scripted = _ScriptedLLM([
        {"role": "assistant", "content": "",
         "tool_calls": [{"id": "c1", "type": "function",
                         "function": {"name": "calculator", "arguments": '{"expression": "1+1"}'}}]},
    ])
    monkeypatch.setattr(rl, "_active_llm", lambda: scripted)
    monkeypatch.setattr(rl, "start_trajectory", lambda *a, **k: None)
    monkeypatch.setattr(rl, "_finish_with_save", lambda *a, **k: None)
    monkeypatch.setattr(rl, "current_trajectory", lambda: None)

    # 取消发生在「第 1 步的工具已执行完」之后：第 1 次 LLM 调用必须发生，
    # 第 2 步在其入口的步间检查处被拦下，不再调用 LLM。
    original_execute = rl.execute_tool_call

    def execute_then_cancel(tool_call):
        result = original_execute(tool_call)
        cancel()
        return result

    monkeypatch.setattr(rl, "execute_tool_call", execute_then_cancel)

    with pytest.raises(LLMCancelled):
        rl.react_loop("q", max_steps=4)
    assert scripted.calls == 1, f"取消后仍调用了 LLM: {scripted.calls} 次"
    assert "cancelled" in [e for e, _ in _events]


# ── 6. HTTP 端到端：断连真正停掉 Agent ──


class _CountingLLM:
    """每次调用耗时可控，用于观察断连后是否还在继续跑。"""

    def __init__(self, step_delay: float):
        self.model = "counting"
        self.api_key = "x"
        self.provider_name = "counting"
        self.calls = 0
        self.step_delay = step_delay

    def chat(self, messages, tool_defs=None, temperature=None,
             max_tokens=None, max_retries=2, on_delta=None):
        self.calls += 1
        # 模拟流式：分片吐字，期间可被取消
        for piece in ("思考", "中", "…"):
            time.sleep(self.step_delay)
            if on_delta:
                on_delta(piece)
        return {"role": "assistant", "content": "", "tool_calls": [
            {"id": f"c{self.calls}", "type": "function",
             "function": {"name": "calculator", "arguments": '{"expression": "1+1"}'}}
        ]}


def _start_server(monkeypatch, llm_stub):
    from react_agent import react_loop as rl
    from react_agent.server.app import AgentHandler

    monkeypatch.setattr(rl, "_active_llm", lambda: llm_stub)
    monkeypatch.setattr(rl, "start_trajectory", lambda *a, **k: None)
    monkeypatch.setattr(rl, "_finish_with_save", lambda *a, **k: None)
    monkeypatch.setattr(rl, "current_trajectory", lambda: None)
    # 显式声明本用例需要的路由配置。REACT_AGENT_SERVER_OFFLINE_REACT 会被
    # tests/test_sse_http.py 在模块顶层设为 "1"（进程级，monkeypatch 不会还原），
    # 若不显式关闭会让 app=default 走离线 ReAct 而不是 LLM 路径。
    monkeypatch.setenv("REACT_AGENT_SERVER_LLM", "1")
    monkeypatch.setenv("REACT_AGENT_SERVER_OFFLINE_REACT", "0")
    monkeypatch.setenv("REACT_AGENT_LLM_STREAM", "1")
    monkeypatch.setenv("REACT_AGENT_DEFAULT_APP", "default")
    monkeypatch.delenv("REACT_AGENT_APP", raising=False)

    server = ThreadingHTTPServer(("127.0.0.1", 0), AgentHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_client_disconnect_stops_agent(monkeypatch):
    """客户端断开 SSE 后，Agent 的 LLM 调用次数必须停止增长。"""
    stub = _CountingLLM(step_delay=0.15)
    server, thread = _start_server(monkeypatch, stub)
    port = server.server_address[1]
    try:
        body = json.dumps({"app": "default", "message": "算一下 1+1", "max_steps": 8}).encode()
        request = (
            f"POST /v1/chat/stream HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
            f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n"
            "Connection: close\r\n\r\n"
        ).encode() + body

        sock = socket.create_connection(("127.0.0.1", port), timeout=10)
        sock.sendall(request)
        sock.recv(4096)          # 读到第一帧即视为已建立
        time.sleep(0.4)          # 让 Agent 跑起来
        sock.close()             # 客户端离开

        time.sleep(0.6)          # 给取消信号传播的时间
        calls_at_disconnect = stub.calls
        time.sleep(1.2)          # 若未取消，这里应该继续增长
        assert stub.calls == calls_at_disconnect, (
            f"断连后 LLM 调用仍在增长: {calls_at_disconnect} -> {stub.calls}"
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_connected_client_keeps_agent_running(monkeypatch):
    """对照组：保持连接时 Agent 会持续多步执行（证明上一用例的停止来自取消）。"""
    stub = _CountingLLM(step_delay=0.05)
    server, thread = _start_server(monkeypatch, stub)
    port = server.server_address[1]
    try:
        body = json.dumps({"app": "default", "message": "算一下 1+1", "max_steps": 4}).encode()
        request = (
            f"POST /v1/chat/stream HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
            f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n"
            "Connection: close\r\n\r\n"
        ).encode() + body
        sock = socket.create_connection(("127.0.0.1", port), timeout=10)
        sock.sendall(request)
        deadline = time.time() + 8
        raw = b""
        while time.time() < deadline:
            chunk = sock.recv(65536)
            if not chunk:
                break
            raw += chunk
            if b"event: done" in raw:
                break
        sock.close()
        text = raw.decode("utf-8", "replace")
        assert stub.calls > 1, f"对照组步数异常: {stub.calls}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


# ── 7. answer_delta 事件经 SSE 真正送达客户端 ──


def test_answer_delta_reaches_sse_client(monkeypatch):
    stub = _CountingLLM(step_delay=0.01)
    server, thread = _start_server(monkeypatch, stub)
    port = server.server_address[1]
    try:
        body = json.dumps({"app": "default", "message": "算一下 1+1", "max_steps": 2}).encode()
        request = (
            f"POST /v1/chat/stream HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
            f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n"
            "Connection: close\r\n\r\n"
        ).encode() + body
        sock = socket.create_connection(("127.0.0.1", port), timeout=10)
        sock.sendall(request)
        deadline = time.time() + 8
        raw = b""
        while time.time() < deadline:
            chunk = sock.recv(65536)
            if not chunk:
                break
            raw += chunk
            if b"event: done" in raw:
                break
        sock.close()
        text = raw.decode("utf-8", "replace")
        assert "event: answer_delta" in text, text[:400]
        assert "思考" in text
    finally:
        server.shutdown()
        thread.join(timeout=5)
