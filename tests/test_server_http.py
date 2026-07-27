"""Smoke-test thin HTTP server (offline /v1/chat)."""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request

os.environ.setdefault("REACT_AGENT_APP", "docs_troubleshoot")
os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")
os.environ.setdefault("REACT_AGENT_DISABLE_MCP", "1")


def test_health_and_chat_offline():
    from http.server import ThreadingHTTPServer

    from react_agent.server.app import AgentHandler
    from react_agent.apps.docs_troubleshoot.index import reset_index
    from react_agent.tools import enable_app_tools

    enable_app_tools()
    reset_index()

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), AgentHandler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    time.sleep(0.15)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as resp:
            health = json.loads(resp.read().decode("utf-8"))
        assert health["status"] == "ok"
        assert "version" in health

        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat",
            data=json.dumps({"message": "缺少 Authorization 返回什么?"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        assert body.get("request_id")
        assert "401" in body.get("answer", "") or "unauthorized" in body.get("answer", "").lower()
        assert body.get("mode") == "offline"

        # invalid path
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/nope", timeout=5)
            assert False, "expected 404"
        except urllib.error.HTTPError as e:
            assert e.code == 404
            err = json.loads(e.read().decode("utf-8"))
            assert err["error"]["code"] == "not_found"
            assert err["error"]["request_id"]
    finally:
        httpd.shutdown()
