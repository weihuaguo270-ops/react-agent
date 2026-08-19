"""Regression test for the HTTP benchmark report contract."""

from __future__ import annotations

import os
import threading

from http.server import ThreadingHTTPServer

from examples.eval.run_http_benchmark import run_http_benchmark
from react_agent.server.app import AgentHandler


def test_http_benchmark_reports_latency_and_status(monkeypatch):
    monkeypatch.setenv("REACT_AGENT_APP", "docs_troubleshoot")
    monkeypatch.setenv("REACT_AGENT_DEFAULT_APP", "docs_troubleshoot")
    monkeypatch.setenv("REACT_AGENT_RAG_MODE", "keyword")
    monkeypatch.setenv("REACT_AGENT_DISABLE_MCP", "1")
    server = ThreadingHTTPServer(("127.0.0.1", 0), AgentHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        report = run_http_benchmark(
            f"http://127.0.0.1:{server.server_port}", requests=8, concurrency=4
        )
        assert report["passed"] is True
        assert report["success_rate"] == 1.0
        assert report["status_counts"] == {200: 8}
        assert report["latency_ms"]["p95"] >= report["latency_ms"]["p50"]
        assert report["throughput_rps"] > 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
