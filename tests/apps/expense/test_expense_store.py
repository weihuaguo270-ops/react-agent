from __future__ import annotations

from react_agent.apps.expense.service import submit_claim
from react_agent.apps.expense.store import ExpenseClaimStore, ExpenseStoreError


def _claim(**overrides):
    value = {
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


def test_claim_store_persists_versions_events_and_reopens(tmp_path):
    path = tmp_path / "expense.sqlite"
    store = ExpenseClaimStore(f"sqlite:///{path}")
    created = store.create(_claim(), actor_id="employee-1", request_id="req-1", idempotency_key="create-1")
    updated = store.update(created["claim_id"], {"amount": 140}, actor_id="employee-1", expected_version=1, request_id="req-2", idempotency_key="update-1")
    assert updated["version"] == 2
    store.close()

    reopened = ExpenseClaimStore(f"sqlite:///{path}")
    loaded = reopened.get(created["claim_id"], actor_id="employee-1")
    assert loaded["version"] == 2
    assert loaded["claim"]["amount"] == 140
    events = reopened.events(created["claim_id"], actor_id="employee-1")
    assert [event["event_type"] for event in events] == ["claim_created", "claim_updated"]
    reopened.close()


def test_claim_store_idempotency_and_version_conflict_have_no_extra_event(tmp_path):
    store = ExpenseClaimStore(f"sqlite:///{tmp_path / 'expense.sqlite'}")
    created = store.create(_claim(), actor_id="employee-1", request_id="req-1", idempotency_key="create-1")
    replay = store.create(_claim(), actor_id="employee-1", request_id="req-replay", idempotency_key="create-1")
    assert replay["claim_id"] == created["claim_id"]
    assert replay["idempotent_replay"] is True
    store.update(created["claim_id"], {"amount": 140}, actor_id="employee-1", expected_version=1, request_id="req-2", idempotency_key="update-1")
    before = store.events(created["claim_id"], actor_id="employee-1")
    try:
        store.update(created["claim_id"], {"amount": 180}, actor_id="employee-1", expected_version=1, request_id="req-3", idempotency_key="update-2")
    except ExpenseStoreError as exc:
        assert exc.code == "claim_version_mismatch"
    else:
        raise AssertionError("expected a version conflict")
    after = store.events(created["claim_id"], actor_id="employee-1")
    assert len(after) == len(before)
    store.close()


def test_submit_persists_decision_without_approving(tmp_path):
    store = ExpenseClaimStore(f"sqlite:///{tmp_path / 'expense.sqlite'}")
    created = store.create(_claim(), actor_id="employee-1", request_id="req-1", idempotency_key="create-1")
    result = submit_claim(store, created["claim_id"], actor_id="employee-1", expected_version=1, request_id="req-2", idempotency_key="submit-1")
    assert result["status"] == "under_review"
    assert result["status"] != "approved"
    assert result["decision_code"] == "approve_manager"
    assert store.get(created["claim_id"], actor_id="employee-1")["status"] == "under_review"
    loaded = store.get(created["claim_id"], actor_id="employee-1")
    assert loaded["decision"]["decision"] == "approve_manager"
    replay = submit_claim(store, created["claim_id"], actor_id="employee-1", expected_version=1, request_id="req-replay", idempotency_key="submit-1")
    assert replay["idempotent_replay"] is True
    events = store.events(created["claim_id"], actor_id="employee-1")
    assert [event["event_type"] for event in events].count("claim_submitted") == 1
    store.close()


def test_submitted_claim_is_immutable_and_idempotency_conflict_is_rejected(tmp_path):
    store = ExpenseClaimStore(f"sqlite:///{tmp_path / 'expense.sqlite'}")
    created = store.create(_claim(), actor_id="employee-1", request_id="req-1", idempotency_key="create-1")
    submit_claim(store, created["claim_id"], actor_id="employee-1", expected_version=1, request_id="req-2", idempotency_key="submit-1")
    try:
        store.update(created["claim_id"], {"amount": 180}, actor_id="employee-1", expected_version=1, request_id="req-3", idempotency_key="update-1")
    except ExpenseStoreError as exc:
        assert exc.code == "claim_not_editable"
    else:
        raise AssertionError("submitted claims must be immutable")
    try:
        store.create({**_claim(), "amount": 999}, actor_id="employee-1", request_id="req-4", idempotency_key="create-1")
    except ExpenseStoreError as exc:
        assert exc.code == "idempotency_conflict"
    else:
        raise AssertionError("idempotency conflict must fail closed")
    store.close()


def test_submit_hard_rejection_is_persisted(tmp_path):
    store = ExpenseClaimStore(f"sqlite:///{tmp_path / 'expense.sqlite'}")
    created = store.create(_claim(has_receipt=False, receipt_refs=[]), actor_id="employee-1", request_id="req-1", idempotency_key="create-1")
    result = submit_claim(store, created["claim_id"], actor_id="employee-1", expected_version=1, request_id="req-2", idempotency_key="submit-1")
    assert result["status"] == "rejected"
    store.close()


def test_submit_review_and_escalation_remain_non_terminal_approval_states(tmp_path):
    store = ExpenseClaimStore(f"sqlite:///{tmp_path / 'expense.sqlite'}")
    review_claim = store.create(_claim(currency="EUR"), actor_id="employee-1", request_id="req-1", idempotency_key="create-review")
    review = submit_claim(
        store,
        review_claim["claim_id"],
        actor_id="employee-1",
        expected_version=1,
        request_id="req-2",
        idempotency_key="submit-review",
    )
    assert review["status"] == "under_review"
    assert review["status"] != "approved"

    escalated_claim = store.create(_claim(amount=190), actor_id="employee-1", request_id="req-3", idempotency_key="create-escalated")
    escalated = store.submit(
        escalated_claim["claim_id"],
        actor_id="employee-1",
        expected_version=1,
        request_id="req-4",
        idempotency_key="submit-escalated",
        workflow_runner=lambda _claim: {
            "run_id": "run-escalated",
            "state": {
                "claim_valid": True,
                "decision_code": "escalated",
                "decision": {"decision": "escalated", "review_required": True},
            },
        },
    )
    assert escalated["status"] == "escalated"
    assert escalated["status"] != "approved"
    assert store.get(review_claim["claim_id"], actor_id="employee-1")["decision"]["decision"] == "needs_review"
    store.close()


def test_review_resolution_survives_store_restart_and_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("REACT_AGENT_APPROVAL_MODE", "auto_allow")
    path = tmp_path / "expense.sqlite"
    store = ExpenseClaimStore(f"sqlite:///{path}")
    created = store.create(_claim(currency="EUR"), actor_id="employee-1", request_id="req-1", idempotency_key="create-1")
    submitted = submit_claim(store, created["claim_id"], actor_id="employee-1", expected_version=1, request_id="req-2", idempotency_key="submit-1")
    approval_id = submitted["approval_id"]
    decision_hash = submitted["review"]["decision"]["decision_hash"]
    store.close()

    reopened = ExpenseClaimStore(f"sqlite:///{path}")
    pending = reopened.list_reviews(claim_id=created["claim_id"])[0]
    assert pending["approval_id"] == approval_id
    assert pending["approval_status"] == "pending"
    resolved = reopened.resolve_review(
        approval_id,
        decision="approve",
        approver_id="manager-1",
        claim_id=created["claim_id"],
        expected_version=1,
        decision_hash=decision_hash,
        request_id="req-3",
        idempotency_key="resolve-1",
        comment="policy checked",
    )
    assert resolved["status"] == "approved"
    assert resolved["resolution"]["approver_id"] == "manager-1"
    replay = reopened.resolve_review(
        approval_id,
        decision="approve",
        approver_id="manager-1",
        claim_id=created["claim_id"],
        expected_version=1,
        decision_hash=decision_hash,
        request_id="req-replay",
        idempotency_key="resolve-1",
        comment="policy checked",
    )
    assert replay["idempotent_replay"] is True
    assert reopened.get(created["claim_id"], actor_id="employee-1")["status"] == "approved"
    assert [event["event_type"] for event in reopened.events(created["claim_id"], actor_id="employee-1")] == [
        "claim_created", "claim_submitted", "review_routed", "review_resolved",
    ]
    reopened.close()


def test_review_resolution_rejects_wrong_hash_and_version_without_side_effect(tmp_path, monkeypatch):
    monkeypatch.setenv("REACT_AGENT_APPROVAL_MODE", "auto_allow")
    store = ExpenseClaimStore(f"sqlite:///{tmp_path / 'expense.sqlite'}")
    created = store.create(_claim(currency="EUR"), actor_id="employee-1", request_id="req-1", idempotency_key="create-1")
    submitted = submit_claim(store, created["claim_id"], actor_id="employee-1", expected_version=1, request_id="req-2", idempotency_key="submit-1")
    approval_id = submitted["approval_id"]
    decision_hash = submitted["review"]["decision"]["decision_hash"]
    before = store.events(created["claim_id"], actor_id="employee-1")
    for expected_version, supplied_hash, code in [(2, decision_hash, "approval_version_mismatch"), (1, "sha256:" + "0" * 64, "decision_invalid")]:
        try:
            store.resolve_review(
                approval_id,
                decision="approve",
                approver_id="manager-1",
                claim_id=created["claim_id"],
                expected_version=expected_version,
                decision_hash=supplied_hash,
                request_id="req-invalid",
                idempotency_key=f"resolve-{code}",
            )
        except ExpenseStoreError as exc:
            assert exc.code == code
        else:
            raise AssertionError("invalid review resolution must fail")
    assert store.get(created["claim_id"], actor_id="employee-1")["status"] == "under_review"
    assert store.events(created["claim_id"], actor_id="employee-1") == before
    store.close()
