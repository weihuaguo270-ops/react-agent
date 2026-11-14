from __future__ import annotations

import asyncio

import httpx
import pytest

pytest.importorskip("fastapi")


def _claim():
    return {
        "category": "meal",
        "amount": 128,
        "currency": "USD",
        "occurred_on": "2026-10-12",
        "description": "client meeting",
        "business_purpose": "client meeting",
        "has_receipt": True,
        "receipt_refs": ["receipt-1"],
        "pre_approved": False,
        "expense_type": "business_meal",
        "participants": ["employee-1"],
    }


def test_expense_claim_http_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setenv("REACT_AGENT_DATABASE_URL", f"sqlite:///{tmp_path / 'expense.sqlite'}")
    from react_agent.server.fastapi_app import create_app

    async def go():
        transport = httpx.ASGITransport(app=create_app(initialize_runtime=False))
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            headers = {"X-Actor-Id": "employee-1", "Idempotency-Key": "create-1"}
            created = await client.post("/v1/expense/claims", headers=headers, json=_claim())
            claim_id = created.json()["claim_id"]
            loaded = await client.get(f"/v1/expense/claims/{claim_id}", headers={"X-Actor-Id": "employee-1"})
            assert loaded.status_code == 200
            updated = await client.patch(
                f"/v1/expense/claims/{claim_id}",
                headers={"X-Actor-Id": "employee-1", "Idempotency-Key": "update-1"},
                json={"expected_version": 1, "amount": 140},
            )
            submitted = await client.post(
                f"/v1/expense/claims/{claim_id}/submit",
                headers={"X-Actor-Id": "employee-1", "Idempotency-Key": "submit-1"},
                json={"expected_version": updated.json()["version"]},
            )
            approval_id = submitted.json()["approval_id"]
            decision_hash = submitted.json()["review"]["decision"]["decision_hash"]
            resolved = await client.post(
                f"/v1/expense/reviews/{approval_id}/resolve",
                headers={"X-Request-Id": "resolve-1", "Idempotency-Key": "resolve-1"},
                json={
                    "decision": "approve",
                    "approver_id": "manager-1",
                    "claim_id": claim_id,
                    "expected_version": 2,
                    "decision_hash": decision_hash,
                    "comment": "reviewed",
                },
            )
            reopened_claim = await client.get(f"/v1/expense/claims/{claim_id}", headers={"X-Actor-Id": "employee-1"})
            events = await client.get(f"/v1/expense/claims/{claim_id}/events", headers={"X-Actor-Id": "employee-1"})
            forbidden = await client.get(f"/v1/expense/claims/{claim_id}", headers={"X-Actor-Id": "employee-2"})
            for method, suffix, body in (
                ("GET", "", None), ("GET", "/events", None),
                ("PATCH", "", {"expected_version": 2, "amount": 130}),
                ("POST", "/submit", {"expected_version": 2}),
            ):
                for target in (claim_id, "missing-claim"):
                    hidden = await client.request(
                        method, f"/v1/expense/claims/{target}{suffix}",
                        headers={"X-Actor-Id": "employee-2", "Idempotency-Key": f"hidden-{target}-{method}"},
                        json=body,
                    )
                    assert hidden.status_code == 404
                    assert hidden.json()["error"]["code"] == "not_found"
                    assert hidden.json()["error"]["message"] == "expense claim not found"
            return created, submitted, resolved, reopened_claim, events, forbidden

    created, submitted, resolved, reopened_claim, events, forbidden = asyncio.run(go())
    assert created.status_code == 201, created.text
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "under_review"
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["review"]["status"] == "approved"
    assert reopened_claim.json()["status"] == "approved"
    assert events.status_code == 200
    assert [event["event_type"] for event in events.json()["events"]] == [
        "claim_created",
        "claim_updated",
        "claim_submitted",
        "review_routed",
        "review_resolved",
    ]
    assert submitted.json()["approval_id"]
    assert forbidden.status_code == 404


def test_expense_form_shell_does_not_open_claim_apis(monkeypatch):
    monkeypatch.setenv("REACT_AGENT_AUTH_TOKEN", "form-shell-test-token")
    from react_agent.server.fastapi_app import create_app
    from react_agent.server.static_files import expense_form_ui_html, expense_ops_ui_html

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(initialize_runtime=False)), base_url="http://127.0.0.1") as client:
            shell = await client.get("/expense")
            assert shell.status_code == 200 and shell.content == expense_form_ui_html()
            assert shell.headers["cache-control"] == "no-store"
            assert "text/html" in shell.headers["content-type"]
            ops = await client.get("/expense/ops")
            assert ops.status_code == 200 and ops.content == expense_ops_ui_html()
            assert ops.headers["cache-control"] == "no-store"
            for method, path in (("GET", "/v1/expense/claims/hidden"), ("POST", "/v1/expense/claims"), ("GET", "/v1/expense/cases"), ("GET", "/ui"), ("POST", "/expense"), ("POST", "/expense/ops")):
                assert (await client.request(method, path)).status_code == 401
            assert (await client.get("/expense", headers={"Host": "evil.example"})).status_code == 421
            assert (await client.get("/expense/ops", headers={"Host": "evil.example"})).status_code == 421

    asyncio.run(go())
