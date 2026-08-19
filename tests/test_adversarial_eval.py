"""Regression checks for prompt-injection refusal and HTTP input boundaries."""

from __future__ import annotations

import os

import pytest

from examples.eval.run_adversarial_eval import run_adversarial_eval


@pytest.fixture()
def adversarial_server():
    from http.server import ThreadingHTTPServer
    import threading
    import time

    os.environ.setdefault("REACT_AGENT_APP", "docs_troubleshoot")
    os.environ.setdefault("REACT_AGENT_DEFAULT_APP", "docs_troubleshoot")
    os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")
    os.environ.setdefault("REACT_AGENT_DISABLE_MCP", "1")
    from react_agent.apps.docs_troubleshoot.index import reset_index
    from react_agent.server.app import AgentHandler
    from react_agent.tools import enable_app_tools

    enable_app_tools()
    reset_index()
    server = ThreadingHTTPServer(("127.0.0.1", 0), AgentHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_adversarial_and_boundary_suite(adversarial_server):
    report = run_adversarial_eval(adversarial_server)
    assert report["passed"] == report["cases"]
    assert report["pass_rate"] == 1.0
