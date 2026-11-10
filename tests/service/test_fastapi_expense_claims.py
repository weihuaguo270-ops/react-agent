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
            events = await client.get(f"/v1/expense/claims/{claim_id}/events", headers={"X-Actor-Id": "employee-1"})
            forbidden = await client.get(f"/v1/expense/claims/{claim_id}", headers={"X-Actor-Id": "employee-2"})
            return created, submitted, events, forbidden

    created, submitted, events, forbidden = asyncio.run(go())
    assert created.status_code == 201, created.text
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "under_review"
    assert events.status_code == 200
    assert [event["event_type"] for event in events.json()["events"]] == ["claim_created", "claim_updated", "claim_submitted"]
    assert forbidden.status_code == 404
