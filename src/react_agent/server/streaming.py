"""Request-local event sink used by the HTTP SSE surface.

The core runtime remains usable without an HTTP server.  When a request is
handled through ``/v1/chat/stream``, the server installs a queue-backed sink in
the worker thread and the runtime emits small, JSON-serializable progress
events through this module.

本模块同时承载**请求级取消信号**：客户端断开 SSE 连接时，写出方置位取消事件，
Agent 循环在步间与流式读取中检查它，避免「用户已离开但 Agent 仍跑完全部步骤」，
从而不再白白消耗 LLM 调用。
"""
from __future__ import annotations

import threading
from contextvars import ContextVar
from typing import Any, Callable, Optional


EventSink = Callable[[str, dict[str, Any]], None]
_sink: ContextVar[Optional[EventSink]] = ContextVar("react_agent_stream_sink", default=None)
_cancel: ContextVar[Optional[threading.Event]] = ContextVar(
    "react_agent_stream_cancel", default=None
)


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
