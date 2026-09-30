"""ASGI contract tests for the optional FastAPI Skill surface."""
from __future__ import annotations

import httpx
import pytest


pytest.importorskip("fastapi")
pytest.importorskip("httpx")


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_fastapi_skill_discovery_context_route_and_safe_run():
    from react_agent.server.fastapi_app import create_app

    api = create_app(initialize_runtime=False)
    transport = httpx.ASGITransport(app=api)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://127.0.0.1"
    ) as client:
        catalog_response = await client.get(
            "/v1/skills", headers={"X-Request-Id": "skills-1"}
        )
        assert catalog_response.status_code == 200
        catalog = catalog_response.json()
        assert catalog["request_id"] == "skills-1"
        assert {item["name"] for item in catalog["skills"]} == {
            "docs_troubleshoot",
            "expense_claim_review",
            "github_delivery",
            "security_triage",
        }
        assert all("instructions" not in item for item in catalog["skills"])

        context_response = await client.get(
            "/v1/skills/docs_troubleshoot?level=full"
        )
        assert context_response.status_code == 200
        context = context_response.json()["context"]
        assert context["input_schema"]["required"] == ["query"]
        assert context["allowed_tools"]
        assert context["instructions"]

        route_response = await client.post(
            "/v1/skills/route", json={"query": "API 401 怎么排障"}
        )
        assert route_response.status_code == 200
        assert route_response.json()["route"]["skill"] == "docs_troubleshoot"
        assert route_response.json()["route"]["confidence"] > 0

        run_response = await client.post(
            "/v1/skills/run",
            json={
                "name": "expense_claim_review",
                "payload": {
                    "claim": {
                        "category": "交通",
                        "amount": 80,
                        "has_receipt": False,
                    }
                },
            },
        )
        assert run_response.status_code == 200
        assert (
            run_response.json()["output"]["decision"] == "reject_no_receipt"
        )

        blocked_response = await client.post(
            "/v1/skills/run", json={"name": "github_delivery", "payload": {}}
        )
        assert blocked_response.status_code == 403
        assert (
            blocked_response.json()["error"]["code"]
            == "skill_requires_controlled_caller"
        )


@pytest.mark.anyio
async def test_fastapi_skill_errors_are_structured():
    from react_agent.server.fastapi_app import create_app

    api = create_app(initialize_runtime=False)
    transport = httpx.ASGITransport(app=api)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://127.0.0.1"
    ) as client:
        missing = await client.get("/v1/skills/does_not_exist?level=full")
        assert missing.status_code == 400
        assert missing.json()["error"]["code"] == "invalid_request"

        unknown = await client.post(
            "/v1/skills/run", json={"name": "does_not_exist", "payload": {}}
        )
        assert unknown.status_code == 404
        assert unknown.json()["error"]["code"] == "not_found"


@pytest.mark.anyio
async def test_fastapi_request_guards_and_stream(monkeypatch):
    from react_agent.server.fastapi_app import create_app

    monkeypatch.setenv("REACT_AGENT_AUTH_TOKEN", "test-key")
    monkeypatch.setenv("REACT_AGENT_MAX_BODY_BYTES", "64")
    api = create_app(initialize_runtime=False)
    transport = httpx.ASGITransport(app=api)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        # Probe endpoints stay public for container orchestration.
        health = await client.get("/health")
        assert health.status_code == 200

        unauthorized = await client.post(
            "/v1/chat", json={"message": "hello"}
        )
        assert unauthorized.status_code == 401
        assert unauthorized.json()["error"]["code"] == "unauthorized"

        oversized = await client.post(
            "/v1/chat",
            content=b"{" + b"\"message\":\"" + b"x" * 100 + b"\"}",
            headers={"Authorization": "Bearer test-key", "Content-Type": "application/json"},
        )
        assert oversized.status_code == 413
        assert oversized.json()["error"]["code"] == "payload_too_large"

        stream = await client.post(
            "/v1/chat/stream",
            json={"message": "hello"},
            headers={"Authorization": "Bearer test-key"},
        )
        assert stream.status_code == 200
        # 终态事件是文档承诺的 done（两面已对齐，见 tests/test_stream_surface_parity.py）
        assert "event: started" in stream.text
        assert "event: done" in stream.text


@pytest.mark.anyio
async def test_fastapi_chat_accepts_structured_application_payload():
    from react_agent.server.fastapi_app import create_app

    def handler(body, request_id):
        return 200, {"app": body.get("app"), "claim": body.get("claim")}

    api = create_app(chat_handler=handler, initialize_runtime=False)
    transport = httpx.ASGITransport(app=api)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        response = await client.post(
            "/v1/chat",
            json={
                "app": "expense",
                "claim": {"category": "交通", "amount": 80, "has_receipt": True},
            },
        )
        assert response.status_code == 200
        assert response.json()["app"] == "expense"
