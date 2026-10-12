from __future__ import annotations

import pytest

from react_agent.apps.expense.domain import (
    ApprovalRecord,
    AuditEvent,
    Claim,
    ContractError,
    Decision,
    ErrorCode,
    Handoff,
    LegacyClaimAdapter,
)


def _claim(**overrides):
    value = {
        "claim_id": "clm-1",
        "version": 1,
        "category": "meal",
        "amount": 128,
        "currency": "USD",
        "occurred_on": "2026-10-12",
        "description": "client meeting meal",
        "business_purpose": "client meeting",
        "has_receipt": True,
        "receipt_refs": ["receipt-1"],
        "pre_approved": False,
        "expense_type": "business_meal",
        "participants": ["A"],
    }
    value.update(overrides)
    return value


def test_claim_is_canonical_and_preserves_category_specific_fields():
    claim = Claim.from_dict(_claim())
    assert claim.category == "meal"
    assert claim.version == 1
    assert claim.to_dict()["expense_type"] == "business_meal"


def test_claim_can_be_submitted_before_a_later_manual_review_decision():
    claim = Claim.from_dict(
        _claim(expense_type="entertainment", occurred_on="2026-10-17")
    )
    assert claim.status == "draft"


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"claim_id": ""}, "claim_id"),
        ({"version": 0}, "version"),
        ({"has_receipt": "yes"}, "has_receipt"),
        ({"occurred_on": "12/10/2026"}, "occurred_on"),
        ({"receipt_refs": []}, "receipt_refs"),
    ],
)
def test_claim_rejects_invalid_common_envelope(changes, message):
    with pytest.raises(ContractError, match=message):
        Claim.from_dict(_claim(**changes))


def test_legacy_adapter_accepts_old_display_category_without_fabricating_identity():
    claim = LegacyClaimAdapter.normalize(
        {"category": "餐饮", "amount": 128, "has_receipt": True}
    )
    assert claim.category == "meal"
    assert claim.currency == "USD"
    assert "claim_id" not in claim.to_dict()
    assert "version" not in claim.to_dict()


def test_decision_hash_is_stable_and_handoff_is_bound_to_it():
    decision = Decision(
        decision="needs_review",
        reasons=("policy_not_covered",),
        decision_source="rules",
        decision_model="expense-rules-v1",
        rule_result="not_covered",
        review_required=True,
        handoff=Handoff("policy_not_covered", "medium", "100-500"),
        claim_id="clm-1",
        claim_version=1,
        policy_version="expense-policy-sim-v1",
    )
    assert decision.decision_hash.startswith("sha256:")
    assert decision.handoff.decision_hash == decision.decision_hash
    restored = Decision.from_dict(decision.to_dict())
    assert restored.decision_hash == decision.decision_hash


def test_decision_requires_handoff_for_review_and_rejects_hash_tampering():
    with pytest.raises(ContractError, match="handoff"):
        Decision(
            decision="needs_review", reasons=("x",), decision_source="rules",
            decision_model="expense-rules-v1", rule_result="not_covered", review_required=True,
        )
    valid = Decision(
        decision="approve_manager", reasons=("has_receipt",), decision_source="rules",
        decision_model="expense-rules-v1", rule_result="matched", claim_id="clm-1", claim_version=1,
        policy_version="expense-policy-sim-v1",
    )
    with pytest.raises(ContractError, match="decision_hash"):
        Decision.from_dict({**valid.to_dict(), "decision_hash": "sha256:bad"})


def test_approval_and_audit_records_are_strictly_bound():
    approval = ApprovalRecord(
        approval_id="apr-1", claim_id="clm-1", claim_version=1,
        decision_hash="sha256:" + "a" * 64, decision="approve",
        approver_id="manager-1", created_at="2026-10-12T10:00:00Z",
    )
    assert approval.to_dict()["decision"] == "approve"
    event = AuditEvent(
        event_id="evt-1", claim_id="clm-1", claim_version=1,
        event_type="decision_created", actor_type="agent", actor_id="agent-1",
        request_id="req-1", idempotency_key="idem-1",
        created_at="2026-10-12T10:00:00Z", metadata={"decision": "approve_manager"},
    )
    assert event.to_dict()["metadata"]["decision"] == "approve_manager"
    with pytest.raises(ContractError, match="approve, reject, or escalate"):
        ApprovalRecord(
            approval_id="apr-1", claim_id="clm-1", claim_version=1,
            decision_hash="sha256:" + "a" * 64, decision="approved",
            approver_id="manager-1", created_at="2026-10-12T10:00:00Z",
        )


def test_error_codes_are_stable_strings():
    assert ErrorCode.INVALID_CLAIM.value == "invalid_claim"
    assert ErrorCode.IDEMPOTENCY_CONFLICT.value == "idempotency_conflict"
