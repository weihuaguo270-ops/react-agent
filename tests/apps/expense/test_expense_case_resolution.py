"""H3: existing approvals, case lifecycle and atomic SQL contracts on both dialects."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Barrier

import pytest
from sqlalchemy import event, update

from react_agent.apps.expense.case_store import CaseActor, ExpenseCaseStore
from react_agent.apps.expense.review import ReviewError, resolve_review
from react_agent.apps.expense.store import ExpenseClaimStore, ExpenseStoreError
from react_agent.safety import approvals
from react_agent.safety.permission_gate import set_approval_credential, set_hitl
from .test_expense_case_operations import (
    REVIEWER, action, error_code, history, unchanged_business, work,  # noqa: F401
)
from .test_expense_case_store import ADMIN, OWNER, seed, storage  # noqa: F401


@pytest.fixture(autouse=True)
def gate(monkeypatch, tmp_path):
    monkeypatch.setenv("REACT_AGENT_PERMISSION_GATE", "1")
    monkeypatch.setenv("REACT_AGENT_APPROVAL_MODE", "auto_allow")
    monkeypatch.setenv("REACT_AGENT_APPROVAL_DIR", str(tmp_path / "approvals"))
    monkeypatch.delenv("REACT_AGENT_STRICT_CONFIRM", raising=False)
    monkeypatch.delenv("REACT_AGENT_SANDBOX_REQUIRED", raising=False)
    set_hitl(None)
    set_approval_credential("")
    approvals.take_pending_approval()
    yield
    set_approval_credential("")
    approvals.take_pending_approval()


@pytest.fixture
def active(work):
    claims, cases, routing, binding, submitted, created, now = work
    assigned = action(cases, created, routing=routing)
    started = action(cases, assigned, "start_case", key="start")
    return claims, cases, routing, binding, submitted, started, now


def resolution(active, **overrides):
    _, cases, _, binding, submitted, started, _ = active
    args = dict(actor=REVIEWER, decision="approve", approval_id=submitted["approval_id"],
        claim_version=binding["claim_version"], decision_hash=binding["decision_hash"],
        expected_case_version=started["case_version"], request_id="h3-resolve",
        idempotency_key="resolve", reason="verified synthetic receipt")
    args.update(overrides)
    return cases.resolve_case(started["case_id"], **args)


def snapshot(active):
    claims, cases, _, binding, _, started, _ = active
    return (unchanged_business(claims, binding), cases.get(started["case_id"], actor=ADMIN),
            history(cases, started), cases.outbox(started["case_id"], actor=ADMIN))


@pytest.mark.parametrize("decision,status", [("approve", "approved"), ("reject", "rejected")])
def test_resolution_uses_existing_review_and_atomic_audit_and_reopen(active, decision, status):
    claims, cases, _, binding, submitted, started, _ = active
    resolved = resolution(active, decision=decision)
    assert resolved["status"] == "resolved"  # Work completed, independent of Claim outcome.
    assert resolved["approval_id"] == submitted["approval_id"]
    assert resolved["assignee_id"] is None and resolved["lock_expires_at"] is None
    assert resolved["case_version"] == started["case_version"] + 1
    assert claims.get(binding["claim_id"], actor_id=OWNER.actor_id)["status"] == status
    reviews = claims.list_reviews(claim_id=binding["claim_id"])
    assert len(reviews) == 1 and reviews[0]["approval_status"] == "resolved"
    assert reviews[0]["resolution"]["approver_id"] == REVIEWER.actor_id
    assert reviews[0]["resolution"]["decision"] == decision
    audit = history(cases, started)[-1]
    assert audit["from_status"] == "in_progress" and audit["to_status"] == "resolved"
    assert audit["metadata"]["approval_id"] == submitted["approval_id"]
    assert audit["metadata"]["claim_status_after"] == status and audit["metadata"]["claim_changed"]
    assert claims.events(binding["claim_id"], actor_id=OWNER.actor_id)[-1]["event_type"] == "review_resolved"
    before = snapshot(active)
    claims._engine.dispose()
    reopened = ExpenseCaseStore(ExpenseClaimStore(engine=claims._engine))
    assert reopened.get(started["case_id"], actor=OWNER) == resolved
    for key in ("resolve", "other-key"):
        error_code("invalid_case_transition", lambda: resolution(active, idempotency_key=key))
    assert snapshot(active) == before


def test_without_approval_can_only_complete_human_work(active):
    claims, cases, _, binding, _, started, _ = active
    before = unchanged_business(claims, binding)
    error_code("approval_binding_mismatch", lambda: resolution(active, approval_id=None))
    error_code("approval_binding_mismatch", lambda: resolution(active, approval_id=None, decision="reject"))
    result = resolution(active, approval_id=None, decision="complete")
    assert result["status"] == "resolved" and result["approval_id"] is None
    assert unchanged_business(claims, binding) == before
    assert history(cases, started)[-1]["metadata"]["claim_changed"] is False


@pytest.mark.parametrize("change,code", [
    ({"approval_id": "missing"}, "claim_not_found"),
    ({"claim_version": 2}, "claim_version_mismatch"),
    ({"decision_hash": "sha256:" + "0" * 64}, "approval_binding_mismatch"),
    ({"expected_case_version": 99}, "case_version_conflict"),
    ({"decision": "approved"}, "invalid_decision"),
    ({"decision": "complete"}, "approval_binding_mismatch"),
])
def test_invalid_binding_or_action_fails_without_writes(active, change, code):
    before = snapshot(active)
    error_code(code, lambda: resolution(active, **change))
    assert snapshot(active) == before


def test_different_claim_approval_and_replaced_case_binding_fail(active):
    claims, cases, _, _, submitted, started, _ = active
    _, other = seed(claims)
    before = snapshot(active)
    error_code("forbidden_claim_access", lambda: resolution(active, approval_id=other["approval_id"]))
    assert snapshot(active) == before
    with claims._engine.begin() as connection:
        connection.execute(update(cases._cases).where(cases._cases.c.case_id == started["case_id"]).values(
            approval_id=submitted["approval_id"]))
    before = snapshot(active)
    error_code("approval_binding_mismatch", lambda: resolution(active, approval_id=other["approval_id"]))
    error_code("approval_binding_mismatch", lambda: resolution(active, approval_id=None, decision="complete"))
    assert snapshot(active) == before


def test_prebound_case_resolves_existing_review(active):
    claims, cases, _, _, submitted, started, _ = active
    with claims._engine.begin() as connection:
        connection.execute(update(cases._cases).where(cases._cases.c.case_id == started["case_id"]).values(
            approval_id=submitted["approval_id"]))
    assert resolution(active)["approval_id"] == submitted["approval_id"]


def test_replaced_claim_version_or_decision_fails_without_writes(active):
    claims, _, _, binding, _, _, _ = active
    with claims._engine.begin() as connection:
        connection.execute(update(claims._claims).where(claims._claims.c.claim_id == binding["claim_id"]).values(current_version=2))
    before = snapshot(active)
    error_code("claim_version_mismatch", lambda: resolution(active))
    assert snapshot(active) == before
    with claims._engine.begin() as connection:
        connection.execute(update(claims._claims).where(claims._claims.c.claim_id == binding["claim_id"]).values(current_version=1))
        connection.execute(update(claims._decisions).where(claims._decisions.c.claim_id == binding["claim_id"]).values(decision_hash="changed"))
    before = snapshot(active)
    error_code("approval_binding_mismatch", lambda: resolution(active))
    assert snapshot(active) == before


def test_role_owner_live_lock_and_state_are_required(active):
    _, cases, routing, binding, _, started, now = active
    for actor in (OWNER, ADMIN, replace(REVIEWER, queue_ids=()), replace(REVIEWER, actor_id="other")):
        before = snapshot(active)
        with pytest.raises(ExpenseStoreError):
            resolution(active, actor=actor)
        assert snapshot(active) == before
    now[0] += timedelta(seconds=901)
    before = snapshot(active)
    error_code("case_not_claimable", lambda: resolution(active))
    assert snapshot(active) == before


def test_operator_cannot_approve_even_when_owning_case(active):
    _, cases, routing, _, _, started, _ = active
    moved = action(cases, started, "transfer_case", key="move", reason="operations work",
        target_queue_id="expense_operations", routing=routing)
    operator = CaseActor("operator", "expense_operator", ("expense_operations",))
    assigned = action(cases, moved, actor=operator, key="ops-claim", routing=routing)
    running = action(cases, assigned, "start_case", actor=operator, key="ops-start")
    before = snapshot(active)
    error_code("permission_denied", lambda: resolution(active, actor=operator, expected_case_version=running["case_version"]))
    assert snapshot(active) == before
    assert resolution(active, actor=operator, expected_case_version=running["case_version"],
        decision="complete", approval_id=None)["status"] == "resolved"


def test_cannot_resolve_assigned_case_before_start(work):
    _, cases, routing, _, _, created, _ = work
    assigned = action(cases, created, routing=routing)
    error_code("invalid_case_transition", lambda: resolution((*work[:5], assigned, work[6])))


def test_existing_resolved_review_cannot_be_reused(active):
    claims, _, _, binding, submitted, _, _ = active
    resolve_review(submitted["approval_id"], claim_id=binding["claim_id"], expected_version=1,
        decision_hash=binding["decision_hash"], decision="reject", approver_id="direct-reviewer", store=claims)
    before = snapshot(active)
    error_code("approval_not_pending", lambda: resolution(active))
    assert snapshot(active) == before


def test_case_event_failure_rolls_back_existing_review_claim_and_binding(active):
    claims, cases, _, _, _, _, _ = active
    before = snapshot(active)
    def fail(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO expense_case_events"):
            raise RuntimeError("case audit unavailable")
    event.listen(claims._engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="case audit unavailable"):
            resolution(active)
    finally:
        event.remove(claims._engine, "before_cursor_execute", fail)
    assert snapshot(active) == before
    assert resolution(active)["status"] == "resolved"


def test_concurrent_resolve_has_one_result_and_one_approval_event(active):
    claims, cases, _, binding, _, started, _ = active
    barrier = Barrier(2)
    def run(i):
        barrier.wait(timeout=10)
        try:
            return resolution(active, decision="approve" if i == 0 else "reject", idempotency_key=f"resolve-{i}")
        except ExpenseStoreError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert sum(isinstance(r, dict) for r in results) == 1
    assert results.count("invalid_case_transition") == 1
    assert sum(e["event_type"] == "case_resolved" for e in history(cases, started)) == 1
    assert sum(e["event_type"] == "review_resolved" for e in claims.events(binding["claim_id"], actor_id=OWNER.actor_id)) == 1


def test_direct_s5_resolution_racing_case_resolution_has_one_approval(active):
    claims, cases, _, binding, submitted, started, _ = active
    barrier = Barrier(2)
    def run(i):
        barrier.wait(timeout=10)
        try:
            if i == 0:
                return resolution(active)
            return resolve_review(submitted["approval_id"], claim_id=binding["claim_id"],
                expected_version=1, decision_hash=binding["decision_hash"], decision="reject",
                approver_id="direct-reviewer", store=claims, idempotency_key="direct-resolution")
        except (ReviewError, ExpenseStoreError) as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert sum(isinstance(r, dict) for r in results) == 1
    assert results.count("approval_not_pending") == 1
    events = claims.events(binding["claim_id"], actor_id=OWNER.actor_id)
    assert sum(e["event_type"] == "review_resolved" for e in events) == 1
    claim = claims.get(binding["claim_id"], actor_id=OWNER.actor_id)
    case = cases.get(started["case_id"], actor=ADMIN)
    assert (claim["status"], case["status"]) in {("approved", "resolved"), ("rejected", "in_progress")}


def authorize_pending():
    record = approvals.take_pending_approval()
    assert record is not None
    assert approvals.resolve(record["approval_id"], decision="approve")[0]
    set_approval_credential(record["approval_id"])
    return record


@pytest.mark.parametrize("decision", ["approve", "complete"])
def test_async_gate_requires_bound_once_credential(active, monkeypatch, decision):
    monkeypatch.setenv("REACT_AGENT_APPROVAL_MODE", "async")
    args = dict(decision=decision, approval_id=None) if decision == "complete" else {}
    before = snapshot(active)
    error_code("permission_denied", lambda: resolution(active, **args))
    assert snapshot(active) == before
    record = authorize_pending()
    assert record["arguments"]["case_id"] == active[5]["case_id"]
    assert record["arguments"]["claim_version"] == 1
    assert record["arguments"]["decision_hash"] == active[3]["decision_hash"]
    assert record["arguments"]["expected_case_version"] == active[5]["case_version"]
    assert resolution(active, **args)["status"] == "resolved"
    assert approvals.get(record["approval_id"])["status"] == "consumed"
    error_code("invalid_case_transition", lambda: resolution(active, **args))


@pytest.mark.parametrize("mode", ["expired", "denied", "used", "wrong_binding", "session"])
def test_expired_denied_reused_or_wrong_credential_fails_closed(active, monkeypatch, mode):
    monkeypatch.setenv("REACT_AGENT_APPROVAL_MODE", "async")
    error_code("permission_denied", lambda: resolution(active))
    record = approvals.take_pending_approval()
    approvals.resolve(record["approval_id"], decision="deny" if mode == "denied" else "approve",
        scope="session" if mode == "session" else "once")
    if mode == "expired":
        value = approvals.get(record["approval_id"])
        value["expires_at"] = 1
        approvals._write(value)
    elif mode == "used":
        assert approvals.consume(record["approval_id"], tool=record["tool"], arguments=record["arguments"], require_once=True)[0]
    elif mode == "wrong_binding":
        value = approvals.get(record["approval_id"])
        value["arguments"]["expected_case_version"] += 1
        approvals._write(value)
    set_approval_credential(record["approval_id"])
    before = snapshot(active)
    error_code("permission_denied", lambda: resolution(active))
    if mode == "session":
        assert not approvals.session_grant_for("tool:resolve_review")
    assert snapshot(active) == before


def test_bound_h3_credential_cannot_be_used_via_legacy_review_call(active, monkeypatch):
    claims, _, _, binding, submitted, _, _ = active
    monkeypatch.setenv("REACT_AGENT_APPROVAL_MODE", "async")
    error_code("permission_denied", lambda: resolution(active))
    record = authorize_pending()
    before = snapshot(active)
    with pytest.raises(ReviewError) as exc:
        resolve_review(submitted["approval_id"], claim_id=binding["claim_id"], expected_version=1,
            decision_hash=binding["decision_hash"], decision="approve", approver_id=REVIEWER.actor_id, store=claims)
    assert exc.value.code == "permission_denied"
    assert approvals.get(record["approval_id"])["status"] == "approved"
    assert snapshot(active) == before
    assert resolution(active)["status"] == "resolved"


def test_database_rollback_does_not_restore_consumed_permission_credential(active, monkeypatch):
    claims = active[0]
    monkeypatch.setenv("REACT_AGENT_APPROVAL_MODE", "async")
    error_code("permission_denied", lambda: resolution(active))
    record = authorize_pending()
    before = snapshot(active)
    def fail(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO expense_case_events"):
            raise RuntimeError("case audit unavailable")
    event.listen(claims._engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="case audit unavailable"):
            resolution(active)
    finally:
        event.remove(claims._engine, "before_cursor_execute", fail)
    assert snapshot(active) == before
    assert approvals.get(record["approval_id"])["status"] == "consumed"
    error_code("permission_denied", lambda: resolution(active))
    authorize_pending()
    assert resolution(active)["status"] == "resolved"


def test_waiting_case_requires_explicit_applicant_resume_without_business_rerun(active):
    claims, cases, routing, binding, _, started, now = active
    before_business = unchanged_business(claims, binding)
    waiting = action(cases, started, "request_applicant", key="wait", reason="need supplemental evidence")
    assert waiting["status"] == "needs_applicant" and waiting["assignee_id"] is None
    now[0] += timedelta(days=2)
    before = snapshot(active)
    error_code("case_not_claimable", lambda: resolution(active, expected_case_version=waiting["case_version"]))
    for op, args in (("transfer_case", dict(reason="no implicit resume", routing=routing)),
                     ("claim_case", dict(routing=routing))):
        error_code("invalid_case_transition", lambda: action(cases, waiting, op, key=op, **args))
    scan = cases.scan_sla(actor=ADMIN, routing=routing, request_id="scan-wait")
    assert scan["cases"] == [] and scan["conflicts"][0]["error_code"] == "invalid_case_transition"
    assert snapshot(active) == before
    args = dict(actor=OWNER, claim_version=1, decision_hash=binding["decision_hash"],
        expected_case_version=waiting["case_version"], request_id="applicant-supplement",
        idempotency_key="resume", evidence_ref="receipt:supplement", reason="evidence supplied", routing=routing)
    with pytest.raises(ExpenseStoreError):
        cases.resume_case(started["case_id"], **{**args, "actor": REVIEWER})
    error_code("claim_version_mismatch", lambda: cases.resume_case(started["case_id"], **{**args, "claim_version": 2}))
    assert snapshot(active) == before
    resumed = cases.resume_case(started["case_id"], **args)
    assert resumed["status"] == "queued" and resumed["assignee_id"] is None
    assert resumed["resolution_due_at"] == waiting["resolution_due_at"]
    assert cases.resume_case(started["case_id"], **args) == {**resumed, "idempotent_replay": True}
    assert unchanged_business(claims, binding) == before_business
    audit = history(cases, started)[-1]
    assert audit["event_type"] == "case_resumed" and audit["metadata"]["business_resumed"] is False
    assert audit["metadata"]["evidence_ref"] == "receipt:supplement"


def test_waiting_old_claim_version_cannot_resume(active):
    claims, cases, routing, binding, _, started, _ = active
    waiting = action(cases, started, "request_applicant", key="wait", reason="evidence needed")
    with claims._engine.begin() as connection:
        connection.execute(update(claims._claims).where(claims._claims.c.claim_id == binding["claim_id"]).values(current_version=2))
    before = snapshot(active)
    error_code("claim_version_mismatch", lambda: cases.resume_case(started["case_id"], actor=OWNER,
        claim_version=1, decision_hash=binding["decision_hash"], expected_case_version=waiting["case_version"],
        request_id="resume", idempotency_key="resume", evidence_ref="receipt:new", reason="new version", routing=routing))
    assert snapshot(active) == before


def test_resume_unavailable_queue_fails_to_unrouted_without_claim_change(active):
    claims, cases, routing, binding, _, started, _ = active
    waiting = action(cases, started, "request_applicant", key="wait", reason="evidence needed")
    unavailable = replace(routing, queues=tuple(replace(q, available=False) if q.queue_id == "finance_review" else q for q in routing.queues))
    before = unchanged_business(claims, binding)
    result = cases.resume_case(started["case_id"], actor=OWNER, claim_version=1,
        decision_hash=binding["decision_hash"], expected_case_version=waiting["case_version"],
        request_id="resume", idempotency_key="resume", evidence_ref="receipt:new", reason="new evidence", routing=unavailable)
    assert result["status"] == "unrouted" and result["error_code"] == "queue_unavailable"
    assert unchanged_business(claims, binding) == before
