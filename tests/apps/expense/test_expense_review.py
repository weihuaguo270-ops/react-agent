from __future__ import annotations

import pytest

from react_agent.apps.expense.review import ReviewError, reset_reviews, resolve_review, route_review


@pytest.fixture(autouse=True)
def _reset():
    reset_reviews()
    yield
    reset_reviews()


def _claim(**overrides):
    value = {
        "claim_id": "review-1", "version": 1, "category": "meal", "amount": 128,
        "currency": "EUR", "occurred_on": "2026-10-12", "description": "client meeting",
        "business_purpose": "client meeting", "has_receipt": True, "receipt_refs": ["r1"],
        "pre_approved": False, "expense_type": "business_meal", "participants": ["employee-1"],
    }
    value.update(overrides)
    return value


def _review_decision():
    return {
        "decision": "needs_review", "reasons": ["policy_not_covered"],
        "decision_source": "rules", "decision_model": "expense-rules-v1",
        "rule_result": "not_covered", "review_required": True,
    }


def test_route_review_creates_non_terminal_pending_record():
    routed = route_review(_claim(), _review_decision(), request_id="req-1", idempotency_key="route-1")
    assert routed["status"] == "under_review"
    assert routed["approval_id"]
    assert routed["approval_status"] == "pending"
    assert routed["events"][0]["event_type"] == "review_routed"


def test_resolve_review_approve_binds_version_hash_and_audit(monkeypatch):
    monkeypatch.setenv("REACT_AGENT_APPROVAL_MODE", "auto_allow")
    routed = route_review(_claim(), _review_decision(), idempotency_key="route-2")
    resolved = resolve_review(
        routed["approval_id"], decision="approve", approver_id="manager-1",
        claim_id="review-1", expected_version=1,
        decision_hash=routed["decision"]["decision_hash"], request_id="req-2", idempotency_key="resolve-2",
        comment="policy checked",
    )
    assert resolved["status"] == "approved"
    assert resolved["resolution"]["approver_id"] == "manager-1"
    assert resolved["events"][-1]["metadata"]["decision_hash"] == routed["decision"]["decision_hash"]


def test_resolve_review_rejects_stale_version_and_hash(monkeypatch):
    monkeypatch.setenv("REACT_AGENT_APPROVAL_MODE", "auto_allow")
    routed = route_review(_claim(), _review_decision(), idempotency_key="route-3")
    with pytest.raises(ReviewError, match="version"):
        resolve_review(routed["approval_id"], decision="approve", approver_id="m", claim_id="review-1", expected_version=2, decision_hash=routed["decision"]["decision_hash"])
    with pytest.raises(ReviewError, match="decision_hash"):
        resolve_review(routed["approval_id"], decision="approve", approver_id="m", claim_id="review-1", expected_version=1, decision_hash="sha256:" + "0" * 64)


def test_escalate_remains_non_terminal_and_replay_is_idempotent(monkeypatch):
    monkeypatch.setenv("REACT_AGENT_APPROVAL_MODE", "auto_allow")
    routed = route_review(_claim(), _review_decision(), idempotency_key="route-4")
    first = resolve_review(routed["approval_id"], decision="escalate", approver_id="manager-1", claim_id="review-1", expected_version=1, decision_hash=routed["decision"]["decision_hash"], idempotency_key="resolve-4")
    assert first["status"] == "escalated"
    replay = resolve_review(routed["approval_id"], decision="escalate", approver_id="manager-1", claim_id="review-1", expected_version=1, decision_hash=routed["decision"]["decision_hash"], idempotency_key="resolve-4")
    assert replay["resolution"] == first["resolution"]
    with pytest.raises(ReviewError, match="already been resolved"):
        resolve_review(routed["approval_id"], decision="approve", approver_id="manager-1", claim_id="review-1", expected_version=1, decision_hash=routed["decision"]["decision_hash"], idempotency_key="resolve-other")
