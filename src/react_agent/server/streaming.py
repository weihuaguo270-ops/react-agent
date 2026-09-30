"""Request-local event sink used by the HTTP SSE surface.

The core runtime remains usable without an HTTP server.  When a request is
handled through ``/v1/chat/stream``, the server installs a queue-backed sink in
the worker thread and the runtime emits small, JSON-serializable progress
events through this module.

本模块同时承载**请求级取消信号**：客户端断开 SSE 连接时，写出方置位取消事件，
Agent 循环在步间与流式读取中检查它，避免「用户已离开但 Agent 仍跑完全部步骤」，
从而不再白白消耗 LLM 调用。

另外，两个服务面（stdlib ``server/app.py`` 与 FastAPI ``server/fastapi_app.py``）
的 **SSE 帧格式**与 **EventSource 查询参数解析**也放在这里共用：格式一旦分叉，
同一个客户端在两个入口点上就会解析出不同的东西。
"""
from __future__ import annotations

import json
import threading
from contextvars import ContextVar
from typing import Any, Callable, Iterable, Optional

#: SSE 心跳间隔（秒）：这么久没有事件就发一帧 ``heartbeat`` 保活。
HEARTBEAT_SECONDS = 10.0


EventSink = Callable[[str, dict[str, Any]], None]
_sink: ContextVar[Optional[EventSink]] = ContextVar("react_agent_stream_sink", default=None)
_cancel: ContextVar[Optional[threading.Event]] = ContextVar(
    "react_agent_stream_cancel", default=None
)


def sse_frame(event: str, data: Optional[dict[str, Any]] = None, event_id: str = "") -> str:
    """构造一帧 SSE 文本。

    ``data`` 按行拆成多个 ``data:`` 字段，因此载荷里的换行不会截断帧；``event_id``
    非空时带上 ``id:`` 字段（服务面按事件序号自增）。
    """
    payload = json.dumps(dict(data or {}), ensure_ascii=False, separators=(",", ":"))
    lines = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.extend(f"data: {line}" for line in payload.splitlines() or [""])
    return "\n".join(lines) + "\n\n"


def query_body(pairs: Iterable[tuple[str, str]]) -> dict[str, Any]:
    """EventSource 查询参数 → 请求体。

    同名参数取**最后一个**（与 ``parse_qs(...)[key][-1]`` 一致），``max_steps``
    转成 int（转不了就原样保留，交给下游校验）。
    """
    body: dict[str, Any] = {}
    for key, value in pairs:
        body[key] = value
    if "max_steps" in body:
        try:
            body["max_steps"] = int(body["max_steps"])
        except (TypeError, ValueError):
            pass
    return body


def install(sink: EventSink):
    """安装事件 sink 与取消事件，返回 ``(tokens, cancel_event)``。

    ``cancel_event`` 必须由调用方持有并传给 :func:`request_cancel`，因为
    ContextVar **不跨线程共享**：SSE 的连接线程与执行 Agent 的 worker 线程各有
    一份上下文，只有直接持有同一个 ``threading.Event`` 对象才能把取消送达 worker。
    """
    event = threading.Event()
    return (_sink.set(sink), _cancel.set(event)), event


def reset(tokens) -> None:
    """还原 ``install()`` 返回的 tokens。"""
    sink_token, cancel_token = tokens
    _sink.reset(sink_token)
    _cancel.reset(cancel_token)


def set_event_sink(sink: Optional[EventSink]):
    """Install a sink for the current request and return its context token."""
    return _sink.set(sink)


def reset_event_sink(token) -> None:
    _sink.reset(token)


def request_cancel(event: Optional[threading.Event] = None) -> None:
    """置位取消信号（幂等）。

    显式传入 ``install()`` 返回的 event 是最可靠的方式；不传时回退到当前上下文的
    event（仅在单线程场景下有效）。
    """
    target = event if event is not None else _cancel.get()
    if target is not None:
        target.set()


def is_cancelled() -> bool:
    """当前请求是否已被取消。未安装取消事件时恒为 False。"""
    event = _cancel.get()
    return bool(event is not None and event.is_set())


def emit_event(event: str, data: Optional[dict[str, Any]] = None) -> None:
    sink = _sink.get()
    if sink is None:
        return
    try:
        sink(event, dict(data or {}))
    except Exception:
        # Streaming must never make the underlying Agent request fail.
        return
