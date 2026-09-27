"""SSE endpoint contract tests for the stdlib HTTP server."""
from __future__ import annotations

import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer


def _events(raw: str):
    out = []
    for block in raw.strip().split("\n\n"):
        fields = {}
        for line in block.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                fields[key] = value.lstrip()
        if "event" in fields and "data" in fields:
            fields["data"] = json.loads(fields["data"])
            out.append(fields)
    return out


def test_post_chat_stream_emits_progress_and_terminal_result(monkeypatch):
    monkeypatch.setenv("REACT_AGENT_SERVER_OFFLINE_REACT", "1")
    monkeypatch.setenv("REACT_AGENT_DEFAULT_APP", "default")
    from react_agent.apps.docs_troubleshoot.index import reset_index
    from react_agent.server.app import AgentHandler
    from react_agent.tools import enable_app_tools

    enable_app_tools()
    reset_index()
    server = ThreadingHTTPServer(("127.0.0.1", 0), AgentHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/v1/chat/stream",
            data=json.dumps({"app": "default", "message": "请用 calculator 工具计算 17*19"}).encode(),
            headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            assert response.status == 200
            assert response.headers["Content-Type"].startswith("text/event-stream")
            assert response.headers["X-Request-Id"]
            events = _events(response.read().decode("utf-8"))
        names = [item["event"] for item in events]
        assert names[0] == "started"
        assert "tool_call" in names
        assert "tool_result" in names
        assert "result" in names
        assert names[-1] == "done"
        result = next(item["data"]["result"] for item in events if item["event"] == "result")
        assert "323" in result["answer"]
        assert events[-1]["data"]["ok"] is True
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_get_chat_stream_supports_eventsource_style_query(monkeypatch):
    monkeypatch.setenv("REACT_AGENT_SERVER_OFFLINE_REACT", "1")
    monkeypatch.setenv("REACT_AGENT_DEFAULT_APP", "default")
    from react_agent.apps.docs_troubleshoot.index import reset_index
    from react_agent.server.app import AgentHandler
    from react_agent.tools import enable_app_tools

    enable_app_tools()
    reset_index()
    server = ThreadingHTTPServer(("127.0.0.1", 0), AgentHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = (
            f"http://127.0.0.1:{server.server_port}/v1/chat/stream"
            "?app=default&message=%E8%AE%A1%E7%AE%97%20100%20-%2037"
        )
        with urllib.request.urlopen(url, timeout=10) as response:
            events = _events(response.read().decode("utf-8"))
        assert events[-1]["event"] == "done"
        result = next(item["data"]["result"] for item in events if item["event"] == "result")
        assert "63" in result["answer"]
    finally:
        server.shutdown()
        thread.join(timeout=5)
