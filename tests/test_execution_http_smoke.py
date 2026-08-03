"""HTTP execution smoke — app=default via offline_react."""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request

os.environ.setdefault("REACT_AGENT_DEFAULT_APP", "docs_troubleshoot")
os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")
os.environ.setdefault("REACT_AGENT_DISABLE_MCP", "1")
os.environ.setdefault("REACT_AGENT_SERVER_OFFLINE_REACT", "1")


def test_offline_react_calculator():
    from react_agent.server.offline_react import offline_react_loop

    out = offline_react_loop("请用 calculator 工具计算 17*19，给出数字答案。")
    assert out["ok"]
    assert "323" in out["answer"]
    assert "calculator" in out["tools_called"]


def test_execution_http_smoke_local_server():
    from http.server import ThreadingHTTPServer

    from react_agent.apps.docs_troubleshoot.index import reset_index
    from react_agent.eval.http_execution import run_execution_http_smoke
    from react_agent.server.app import AgentHandler
    from react_agent.tools import enable_app_tools

    enable_app_tools()
    reset_index()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), AgentHandler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    time.sleep(0.15)
    try:
        base = f"http://127.0.0.1:{port}"
        report = run_execution_http_smoke(
            base,
            only_ids={"agent_calc_17x19", "agent_calc_100_minus_37"},
        )
        assert report["summary"]["passed"] == report["summary"]["total"]
        assert report["summary"]["total"] == 2

        req = urllib.request.Request(
            f"{base}/v1/chat",
            data=json.dumps({"app": "default", "message": "hello"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=10)
            assert False, "expected 501"
        except urllib.error.HTTPError as e:
            assert e.code == 501
            err = json.loads(e.read().decode("utf-8"))
            assert err["error"]["code"] == "not_implemented"
    finally:
        httpd.shutdown()


def test_default_app_requires_mode_without_offline_or_llm():
    from http.server import ThreadingHTTPServer

    from react_agent.apps.docs_troubleshoot.index import reset_index
    from react_agent.server.app import AgentHandler
    from react_agent.tools import enable_app_tools

    old = os.environ.pop("REACT_AGENT_SERVER_OFFLINE_REACT", None)
    enable_app_tools()
    reset_index()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), AgentHandler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    time.sleep(0.15)
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat",
            data=json.dumps({"app": "default", "message": "test"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=5)
            assert False, "expected 400"
        except urllib.error.HTTPError as e:
            assert e.code == 400
            err = json.loads(e.read().decode("utf-8"))
            assert err["error"]["code"] == "invalid_request"
    finally:
        httpd.shutdown()
        if old is not None:
            os.environ["REACT_AGENT_SERVER_OFFLINE_REACT"] = old
