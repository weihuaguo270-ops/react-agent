from __future__ import annotations

import asyncio

import httpx
import pytest

pytest.importorskip("fastapi")


def _claim():
    return {
        "claim_id": "http-review-1", "version": 1, "category": "meal", "amount": 128,
        "currency": "EUR", "occurred_on": "2026-10-12", "description": "client meeting",
        "business_purpose": "client meeting", "has_receipt": True, "receipt_refs": ["r1"],
        "pre_approved": False, "expense_type": "business_meal", "participants": ["employee-1"],
    }


def test_expense_review_endpoint_is_domain_specific(monkeypatch):
    monkeypatch.setenv("REACT_AGENT_APPROVAL_MODE", "auto_allow")
    from react_agent.apps.expense.review import route_review, reset_reviews
    from react_agent.server.fastapi_app import create_app

    reset_reviews()
    routed = route_review(_claim(), {"decision": "needs_review", "reasons": ["policy_not_covered"], "decision_source": "rules", "decision_model": "expense-rules-v1", "rule_result": "not_covered", "review_required": True}, idempotency_key="http-route")
    async def go():
        transport = httpx.ASGITransport(app=create_app(initialize_runtime=False))
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            response = await client.post(
                f"/v1/expense/reviews/{routed['approval_id']}/resolve",
                headers={"X-Approval-Credential": "unused-generic-credential"},
                json={"decision": "approve", "approver_id": "manager-1", "claim_id": "http-review-1", "expected_version": 1, "decision_hash": routed["decision"]["decision_hash"], "comment": "checked", "idempotency_key": "http-resolve"},
            )
            return response

    response = asyncio.run(go())
    assert response.status_code == 200, response.text
    assert response.json()["review"]["status"] == "approved"
    assert response.json()["review"]["resolution"]["approver_id"] == "manager-1"
    reset_reviews()
