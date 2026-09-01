"""HTTP API tests for Skill discovery, routing, and safe execution."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request


def _request(url: str, *, method: str = "GET", payload: dict | None = None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method=method,
    )
    return urllib.request.urlopen(request, timeout=10)


def test_skill_http_discovery_route_and_safe_run():
    from http.server import ThreadingHTTPServer

    from react_agent.server.app import AgentHandler
    from react_agent.apps.docs_troubleshoot.index import reset_index

    reset_index()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), AgentHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    try:
        with _request(f"{base}/v1/skills") as response:
            catalog = json.loads(response.read().decode("utf-8"))
        names = {item["name"] for item in catalog["skills"]}
        assert names == {
            "docs_troubleshoot",
            "expense_claim_review",
            "github_delivery",
            "security_triage",
        }
        docs = next(item for item in catalog["skills"] if item["name"] == "docs_troubleshoot")
        assert "instructions" not in docs

        with _request(f"{base}/v1/skills/docs_troubleshoot?level=full") as response:
            full = json.loads(response.read().decode("utf-8"))
        assert full["context"]["input_schema"]["required"] == ["query"]
        assert full["context"]["allowed_tools"]

        with _request(
            f"{base}/v1/skills/route",
            method="POST",
            payload={"query": "API 401 怎么排障"},
        ) as response:
            route = json.loads(response.read().decode("utf-8"))
        assert route["route"]["skill"] == "docs_troubleshoot"
        assert route["route"]["confidence"] > 0

        with _request(
            f"{base}/v1/skills/run",
            method="POST",
            payload={
                "name": "expense_claim_review",
                "payload": {"claim": {"category": "交通", "amount": 80, "has_receipt": False}},
            },
        ) as response:
            expense = json.loads(response.read().decode("utf-8"))
        assert expense["ok"] is True
        assert expense["output"]["decision"] == "reject_no_receipt"

        try:
            _request(
                f"{base}/v1/skills/run",
                method="POST",
                payload={"name": "github_delivery", "payload": {}},
            )
            raise AssertionError("expected external-write Skill to be rejected")
        except urllib.error.HTTPError as error:
            assert error.code == 403
            blocked = json.loads(error.read().decode("utf-8"))
            assert blocked["error"]["code"] == "skill_requires_controlled_caller"
    finally:
        httpd.shutdown()
