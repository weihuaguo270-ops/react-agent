"""Expense app — offline approval path."""
from __future__ import annotations

import os

os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")


def test_expense_approve_manager():
    from react_agent.apps.expense.offline_answer import answer_offline

    out = answer_offline(
        {"claim": {"category": "餐饮", "amount": 128, "has_receipt": True}}
    )
    assert out["ok"]
    assert out["decision"] == "approve_manager"
    assert not out["refused"]


def test_expense_reject_no_receipt():
    from react_agent.apps.expense.offline_answer import answer_offline

    out = answer_offline(
        {"claim": {"category": "交通", "amount": 80, "has_receipt": False}}
    )
    assert out["decision"] == "reject_no_receipt"
    assert out["refused"]


def test_expense_server_route():
    import threading
    import time
    import urllib.request
    import json
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
        body = json.dumps(
            {
                "app": "expense",
                "claim": {"category": "餐饮", "amount": 128, "has_receipt": True},
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        assert data.get("app") == "expense"
        assert data.get("decision") == "approve_manager"
    finally:
        httpd.shutdown()
