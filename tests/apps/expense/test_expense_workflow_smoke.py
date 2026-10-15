from __future__ import annotations

import copy

import pytest

from react_agent.apps.expense.workflow import (
    EXPENSE_WORKFLOW_NAME,
    SimulationEvidenceAdapter,
    reset_decision_audit,
)
from react_agent.workflow import list_workflows, run_workflow


@pytest.fixture(autouse=True)
def _reset_audit():
    reset_decision_audit()
    yield
    reset_decision_audit()


def _claim(**overrides):
    value = {
        "claim_id": "S3-001",
        "claim_version": 1,
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
    value.update(overrides)
    return value


def test_expense_workflow_is_registered_with_stable_versioned_name():
    item = next(item for item in list_workflows() if item["name"] == EXPENSE_WORKFLOW_NAME)
    assert item["version"] == "1"
    assert item["steps"] == "5"


def test_s3_workflow_smoke_approves_normal_claim_and_records_audit():
    result = run_workflow(EXPENSE_WORKFLOW_NAME, {"claim": _claim(), "idempotency_key": "s3:approve:1"})
    assert result.ok
    assert result.state["decision_code"] == "approve_manager"
    assert result.state["decision_audit"]["idempotent_replay"] is False
    assert [step.step_id for step in result.steps] == [
        "ingest_claim", "load_policy_facts", "decide", "persist_decision", "finalize"
    ]


def test_s3_workflow_smoke_handles_hard_rejection_and_review():
    rejected = run_workflow(
        EXPENSE_WORKFLOW_NAME,
        {"claim": _claim(has_receipt=False, receipt_refs=[]), "idempotency_key": "s3:reject:1"},
    )
    assert rejected.ok
    assert rejected.state["decision_code"] == "reject_no_receipt"
    assert rejected.refused is True

    review = run_workflow(
        EXPENSE_WORKFLOW_NAME,
        {"claim": _claim(currency="EUR"), "idempotency_key": "s3:review:1"},
    )
    assert review.ok
    assert review.state["decision_code"] == "needs_review"
    assert review.state["decision"]["review_required"] is True


def test_s3_workflow_smoke_invalid_claim_skips_decision_nodes():
    result = run_workflow(
        EXPENSE_WORKFLOW_NAME,
        {"claim": _claim(description=None)},
    )
    assert result.ok
    assert result.state["claim_valid"] is False
    assert result.state["error_code"] == "invalid_claim"
    assert result.steps[3].output["skipped"] is True


def test_s3_workflow_fails_closed_when_policy_is_unavailable(monkeypatch):
    import react_agent.apps.expense.workflow as workflow

    def broken_policy(**_kwargs):
        raise workflow.PolicyContractError("fixture missing")

    monkeypatch.setattr(workflow, "load_policy_facts", broken_policy)
    result = run_workflow(EXPENSE_WORKFLOW_NAME, {"claim": _claim()})
    assert result.ok is False
    assert result.state["failed_step"] == "load_policy_facts"
    assert result.state["error_code"] == "policy_unavailable"
    assert result.state["refused"] is True


def test_s3_workflow_fails_closed_on_unknown_decision_code(monkeypatch):
    import react_agent.apps.expense.workflow as workflow

    monkeypatch.setattr(workflow, "decide", lambda *_args, **_kwargs: "approve_unknown")
    result = run_workflow(EXPENSE_WORKFLOW_NAME, {"claim": _claim(), "idempotency_key": "s3:unknown:1"})
    assert result.ok is False
    assert result.state["failed_step"] == "decide"
    assert result.state["error_code"] == "invalid_decision"


def test_s3_workflow_idempotent_replay_and_conflict_have_no_second_write():
    claim = _claim()
    first = run_workflow(EXPENSE_WORKFLOW_NAME, {"claim": claim, "idempotency_key": "s3:replay:1"})
    replay = run_workflow(EXPENSE_WORKFLOW_NAME, {"claim": copy.deepcopy(claim), "idempotency_key": "s3:replay:1"})
    assert first.state["decision_audit"]["idempotent_replay"] is False
    assert replay.ok
    assert replay.state["decision_audit"]["idempotent_replay"] is True

    conflict = run_workflow(
        EXPENSE_WORKFLOW_NAME,
        {"claim": _claim(amount=180), "idempotency_key": "s3:replay:1"},
    )
    assert conflict.ok is False
    assert conflict.state["failed_step"] == "persist_decision"
    assert conflict.state["error_code"] == "idempotency_conflict"


def test_s3_adapter_does_not_trust_client_purchase_verification():
    claim = _claim(
        category="office_purchase",
        amount=100,
        business_purpose="office operations",
        purchase_order_id="PO-999",
        item_type="stationery",
        purchase_order_verified=True,
    )
    without_adapter = run_workflow(EXPENSE_WORKFLOW_NAME, {"claim": claim, "idempotency_key": "s3:po:unavailable"})
    assert without_adapter.ok
    assert without_adapter.state["decision_code"] == "needs_review"
    assert without_adapter.state["external_adapter"]["status"] == "unavailable"

    with_adapter = run_workflow(EXPENSE_WORKFLOW_NAME, {
        "claim": claim,
        "evidence_adapter": SimulationEvidenceAdapter(purchase_orders={"PO-999": True}),
        "idempotency_key": "s3:po:verified",
    })
    assert with_adapter.ok
    assert with_adapter.state["decision_code"] == "approve_manager"
    assert with_adapter.state["external_adapter"]["status"] == "verified"


@pytest.mark.parametrize(
    ("purchase_orders", "expected_status", "expected_decision"),
    [({}, "unavailable", "needs_review"), ({"PO-999": False}, "unverified", "needs_review")],
)
def test_s3_purchase_adapter_unknown_or_unverified_fact_never_auto_approves(
    purchase_orders, expected_status, expected_decision
):
    claim = _claim(
        category="office_purchase",
        amount=100,
        business_purpose="office operations",
        purchase_order_id="PO-999",
        item_type="stationery",
        purchase_order_verified=True,
    )
    result = run_workflow(
        EXPENSE_WORKFLOW_NAME,
        {
            "claim": claim,
            "evidence_adapter": SimulationEvidenceAdapter(purchase_orders=purchase_orders),
            "idempotency_key": f"s3:po:{expected_status}",
        },
    )
    assert result.ok
    assert result.state["external_adapter"]["status"] == expected_status
    assert result.state["decision_code"] == expected_decision


def test_s3_quote_adapter_supplies_trusted_price_and_missing_quote_reviews():
    claim = _claim(
        category="transport",
        transport_mode="flight",
        route_scope="inter_city",
        seat_class="economy",
        amount=120,
        expense_type=None,
    )
    unavailable = run_workflow(
        EXPENSE_WORKFLOW_NAME,
        {"claim": claim, "idempotency_key": "s3:quote:missing"},
    )
    verified = run_workflow(
        EXPENSE_WORKFLOW_NAME,
        {
            "claim": claim,
            "evidence_adapter": SimulationEvidenceAdapter(market_prices={"S3-001": 100}),
            "idempotency_key": "s3:quote:verified",
        },
    )
    assert unavailable.state["external_adapter"]["status"] == "unavailable"
    assert unavailable.state["decision_code"] == "needs_review"
    assert verified.state["external_adapter"]["status"] == "verified"
    assert verified.state["decision_code"] == "approve_manager"


def test_s3_http_vertical_slice_can_select_workflow_engine(monkeypatch):
    from react_agent.server.chat_router import handle_chat

    monkeypatch.setenv("REACT_AGENT_EXPENSE_ENGINE", "workflow")
    status, payload = handle_chat(
        {"app": "expense", "claim": _claim(), "idempotency_key": "s3:http:1"},
        "req-s3-http",
    )
    assert status == 200
    assert payload["ok"] is True
    assert payload["mode"] == "workflow"
    assert payload["workflow"] == EXPENSE_WORKFLOW_NAME
    assert payload["decision"] == "approve_manager"
    assert payload["workflow_steps"][-1]["step_id"] == "finalize"


def test_s3_http_legacy_engine_remains_selectable(monkeypatch):
    from react_agent.server.chat_router import handle_chat

    monkeypatch.setenv("REACT_AGENT_EXPENSE_ENGINE", "legacy")
    status, payload = handle_chat(
        {"app": "expense", "claim": {"category": "餐饮", "amount": 128, "has_receipt": True}},
        "req-s3-legacy",
    )
    assert status == 200
    assert payload["decision"] == "approve_manager"
    assert payload["mode"] == "offline"


def test_s3_decision_audit_write_is_registered_as_notify():
    from react_agent.safety.permissions import PermissionLevel, get_tool_permission

    assert get_tool_permission("persist_decision") is PermissionLevel.NOTIFY
