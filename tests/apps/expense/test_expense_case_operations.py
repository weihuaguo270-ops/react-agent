"""H2 contracts reuse H1's SQLite / isolated PostgreSQL setup."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest
from sqlalchemy import delete, event, select, update

from react_agent.apps.expense.case_store import CaseActor, ExpenseCaseStore
from react_agent.apps.expense.store import ExpenseClaimStore, ExpenseStoreError
from .test_expense_case_store import ADMIN, OWNER, create_case, seed, storage  # noqa: F401

REVIEWER = CaseActor("reviewer", "finance_reviewer", ("finance_review",))
FINANCE = CaseActor("finance", "finance_admin", ("finance_admin",))
OPS = CaseActor("ops", "expense_operator", ("expense_operations",))
START = datetime(2026, 11, 12, tzinfo=timezone.utc)


@pytest.fixture
def work(storage):
    claims, cases, routing = storage
    now = [START]
    cases._clock = lambda: now[0]
    binding, submitted, created = create_case(storage)
    return claims, cases, routing, binding, submitted, created, now


def action(cases, created, operation="claim_case", *, actor=REVIEWER, key="action", **kw):
    args = dict(actor=actor, expected_case_version=created["case_version"],
                request_id="h2-request", idempotency_key=key)
    args.update(kw)
    return getattr(cases, operation)(created["case_id"], **args)


def error_code(code, call):
    with pytest.raises(ExpenseStoreError) as exc:
        call()
    assert exc.value.code == code


def history(cases, created):
    return cases.events(created["case_id"], actor=ADMIN)


def unchanged_business(claims, binding):
    return (claims.get(binding["claim_id"], actor_id=OWNER.actor_id),
            claims.events(binding["claim_id"], actor_id=OWNER.actor_id),
            claims.list_reviews(claim_id=binding["claim_id"]))


def test_concurrent_self_claim_has_exactly_one_winner(work):
    claims, cases, routing, binding, _, created, _ = work
    before = unchanged_business(claims, binding)
    barrier = Barrier(4)
    def attempt(i):
        barrier.wait(timeout=10)
        actor = replace(REVIEWER, actor_id=f"reviewer-{i}")
        try:
            return action(cases, created, actor=actor, key=f"claim-{i}", routing=routing)
        except ExpenseStoreError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(attempt, range(4)))
    winners = [r for r in results if isinstance(r, dict)]
    assert len(winners) == 1
    assert results.count("case_already_claimed") == 3
    winner = winners[0]
    assert winner["status"] == "assigned" and winner["case_version"] == 2
    assert winner["lock_expires_at"] == "2026-11-12T00:15:00Z"
    assert [e["event_type"] for e in history(cases, created)] == ["case_created", "case_claimed"]
    assert unchanged_business(claims, binding) == before


def test_identity_membership_role_and_no_assignee_input(work):
    _, cases, routing, _, _, created, _ = work
    for actor in (OWNER, ADMIN, replace(REVIEWER, queue_ids=()),
                  CaseActor("wrong-role", "expense_operator", ("finance_review",))):
        with pytest.raises(ExpenseStoreError):
            action(cases, created, actor=actor, routing=routing)
    with pytest.raises(TypeError, match="assignee_id"):
        action(cases, created, routing=routing, assignee_id="other")
    assert len(history(cases, created)) == 1
    changed = replace(routing, queues=tuple(replace(q, allowed_roles=("finance_admin",))
        if q.queue_id == "finance_review" else q for q in routing.queues))
    error_code("queue_not_allowed", lambda: action(cases, created, routing=changed))
    assert len(history(cases, created)) == 1


def test_action_replay_conflict_version_and_release_are_atomic(work):
    claims, cases, routing, binding, _, created, _ = work
    before = unchanged_business(claims, binding)
    error_code("case_version_conflict", lambda: action(cases, created, routing=routing, expected_case_version=9))
    first = action(cases, created, routing=routing)
    replay = action(cases, created, routing=routing, request_id="retry")
    assert replay == {**first, "idempotent_replay": True}
    error_code("idempotency_conflict", lambda: action(cases, created, routing=routing, expected_case_version=2))
    error_code("case_not_found", lambda: action(cases, created, routing=routing, actor=replace(REVIEWER, actor_id="thief")))
    error_code("case_already_claimed", lambda: action(cases, first, "release_case", key="release",
        actor=replace(REVIEWER, actor_id="other"), reason="unavailable"))
    released = action(cases, first, "release_case", key="release", reason="shift ended")
    assert (released["status"], released["assignee_id"], released["lock_expires_at"]) == ("queued", None, None)
    assert released["responded_at"] == first["responded_at"]
    assert action(cases, first, "release_case", key="release", reason="shift ended")["idempotent_replay"]
    assert len(history(cases, created)) == 3
    assert unchanged_business(claims, binding) == before


def test_transfer_full_audit_dynamic_read_scope_and_sla_snapshot(work):
    claims, cases, routing, binding, _, created, _ = work
    before = unchanged_business(claims, binding)
    claimed = action(cases, created, routing=routing)
    changed = replace(routing, routing_rule_version="routing-v2", queues=tuple(
        replace(q, sla=replace(q.sla, sla_policy_version="sla-v2", response_sla_seconds=60))
        for q in routing.queues))
    error_code("invalid_handoff", lambda: action(cases, claimed, "transfer_case",
        key="transfer", routing=changed, reason=" "))
    result = action(cases, claimed, "transfer_case", key="transfer", routing=changed,
        reason="requires senior review", target_queue_id="finance_admin")
    assert (result["status"], result["queue_id"], result["assignee_id"]) == ("queued", "finance_admin", None)
    assert result["initial_queue_id"] == "finance_review"
    assert result["routing_rule_version"] == "routing-v2"
    for key in ("sla", "response_due_at", "resolution_due_at"):
        assert result[key] == created[key]
    last = history(cases, created)[-1]
    assert (last["from_status"], last["to_status"], last["actor_id"]) == ("assigned", "queued", REVIEWER.actor_id)
    assert last["metadata"].items() >= {"from_queue": "finance_review", "to_queue": "finance_admin",
        "reason": "requires senior review", "previous_assignee_id": REVIEWER.actor_id,
        "assignee_id": None, "previous_case_version": 2, "case_version": 3}.items()
    error_code("case_not_found", lambda: cases.get(created["case_id"], actor=REVIEWER))
    assert cases.get(created["case_id"], actor=FINANCE) == result
    assert cases.list_cases(actor=REVIEWER) == []
    replay = action(cases, claimed, "transfer_case", key="transfer", routing=changed,
        reason="requires senior review", target_queue_id="finance_admin")
    assert replay == {**result, "idempotent_replay": True}
    assert len(history(cases, created)) == 3
    assert unchanged_business(claims, binding) == before


@pytest.mark.parametrize("missing", [False, True])
def test_no_route_and_unavailable_target_fail_closed(work, missing):
    claims, cases, routing, binding, _, created, _ = work
    before = unchanged_business(claims, binding)
    config = replace(routing, rules=()) if missing else replace(routing, queues=tuple(
        replace(q, available=False) if q.queue_id == "finance_admin" else q for q in routing.queues))
    result = action(cases, created, "transfer_case", routing=config, reason="manual verification",
        target_queue_id=None if missing else "finance_admin")
    assert (result["status"], result["queue_id"], result["priority"]) == ("unrouted", None, "high")
    assert result["error_code"] == ("unrouted_case" if missing else "queue_unavailable")
    pending = cases.outbox(created["case_id"], actor=OPS)
    assert next(p for p in pending if p["notification_type"] == "case_unrouted")["target_queue"] == "expense_operations"
    assert unchanged_business(claims, binding) == before


def test_claim_current_queue_unavailable_fails_closed_and_unknown_target_rejected(work):
    _, cases, routing, _, _, created, _ = work
    error_code("queue_not_allowed", lambda: action(cases, created, "transfer_case", routing=routing,
        reason="retry", target_queue_id="unknown"))
    config = replace(routing, queues=tuple(replace(q, available=False) for q in routing.queues))
    result = action(cases, created, routing=config)
    assert result["status"] == "unrouted" and result["assignee_id"] is None
    assert result["error_code"] == "queue_unavailable"


def test_manual_escalation_requires_holder_and_controlled_queue(work):
    claims, cases, routing, binding, _, created, _ = work
    before = unchanged_business(claims, binding)
    claimed = action(cases, created, routing=routing)
    error_code("case_already_claimed", lambda: action(cases, claimed, "escalate_case",
        key="escalate", routing=routing, reason="policy exception", actor=replace(REVIEWER, actor_id="other")))
    result = action(cases, claimed, "escalate_case", key="escalate", routing=routing, reason="policy exception")
    assert (result["status"], result["queue_id"], result["escalation_level"]) == ("escalated", "finance_admin", 1)
    assert result["assignee_id"] is None
    # H0 escalated must first return to queued before self-claim.
    error_code("case_not_claimable", lambda: action(cases, result, actor=FINANCE, key="claim2", routing=routing))
    queued = action(cases, result, "transfer_case", actor=FINANCE, key="resume", routing=routing,
        reason="accept escalated case", target_queue_id="finance_admin")
    assert action(cases, queued, actor=FINANCE, key="claim3", routing=routing)["status"] == "assigned"
    assert unchanged_business(claims, binding) == before


def test_expired_lease_only_unlocks_and_survives_reopen(work):
    claims, cases, routing, binding, _, created, now = work
    before = unchanged_business(claims, binding)
    claimed = action(cases, created, routing=routing)
    claims._engine.dispose()
    reopened = ExpenseCaseStore(ExpenseClaimStore(engine=claims._engine), clock=lambda: now[0])
    assert reopened.get(created["case_id"], actor=OWNER) == claimed
    assert action(reopened, created, routing=routing) == {**claimed, "idempotent_replay": True}
    now[0] += timedelta(minutes=15)
    result = reopened.scan_sla(actor=ADMIN, routing=routing, request_id="scan")["cases"][0]
    assert (result["status"], result["assignee_id"], result["escalation_level"]) == ("queued", None, 0)
    assert result["response_due_at"] == created["response_due_at"]
    assert history(cases, created)[-1]["event_type"] == "claim_lock_expired"
    assert not reopened.scan_sla(actor=ADMIN, routing=routing, request_id="retry")["cases"]
    assert unchanged_business(claims, binding) == before


def test_response_then_resolution_scan_idempotent_and_never_approves(work):
    claims, cases, routing, binding, _, created, now = work
    before = unchanged_business(claims, binding)
    assert created["response_due_at"] == "2026-11-12T04:00:00Z"
    assert created["resolution_due_at"] == "2026-11-13T00:00:00Z"
    now[0] += timedelta(hours=4)
    response = cases.scan_sla(actor=ADMIN, routing=routing, request_id="response")["cases"][0]
    assert response["response_breached"] and response["status"] == "queued"
    assert response["escalation_level"] == 0
    now[0] += timedelta(hours=20)
    resolution = cases.scan_sla(actor=ADMIN, routing=routing, request_id="resolution")["cases"][0]
    assert resolution["resolution_breached"] and resolution["status"] == "escalated"
    assert resolution["queue_id"] == "finance_admin"
    events = history(cases, created)
    pending = cases.outbox(created["case_id"], actor=ADMIN)
    claims._engine.dispose()
    reopened = ExpenseCaseStore(ExpenseClaimStore(engine=claims._engine), clock=lambda: now[0])
    assert reopened.scan_sla(actor=ADMIN, routing=routing, request_id="repeat")["cases"] == []
    assert history(reopened, created) == events
    assert reopened.outbox(created["case_id"], actor=ADMIN) == pending
    assert all(p["status"] == "pending" for p in pending)
    assert unchanged_business(claims, binding) == before


@pytest.mark.parametrize("unavailable", [False, True])
def test_concurrent_overdue_scans_emit_one_escalation_and_one_breach_per_deadline(work, unavailable):
    claims, cases, routing, binding, _, created, now = work
    before = unchanged_business(claims, binding)
    now[0] += timedelta(days=2)
    if unavailable:
        routing = replace(routing, queues=tuple(replace(q, available=False)
            if q.queue_id == "finance_admin" else q for q in routing.queues))
    barrier = Barrier(3)
    def scan(i):
        barrier.wait(timeout=10)
        return cases.scan_sla(actor=ADMIN, routing=routing, request_id=f"scan-{i}")
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(scan, range(3)))
    assert sum(len(r["cases"]) for r in results) == 1
    kinds = [e["event_type"] for e in history(cases, created)]
    assert kinds.count("sla_response_breached") == kinds.count("sla_resolution_breached") == 1
    assert kinds.count("case_unrouted" if unavailable else "case_escalated") == 1
    assert cases.get(created["case_id"], actor=OWNER)["status"] == ("unrouted" if unavailable else "escalated")
    assert unchanged_business(claims, binding) == before


def test_claim_response_prevents_response_breach_but_not_resolution_timeout(work):
    _, cases, routing, _, _, created, now = work
    action(cases, created, routing=routing)
    now[0] += timedelta(days=2)
    result = cases.scan_sla(actor=ADMIN, routing=routing, request_id="overdue")["cases"][0]
    assert not result["response_breached"] and result["resolution_breached"]
    assert result["status"] == "escalated" and result["assignee_id"] is None


def test_first_route_of_unrouted_case_anchors_sla_at_original_creation(work):
    claims, cases, routing, _, _, _, now = work
    binding, _ = seed(claims)
    created = cases.create(**binding, actor=OWNER, routing=replace(routing, rules=()), request_id="unrouted")
    assert created["response_due_at"] is created["resolution_due_at"] is None
    now[0] += timedelta(days=2)
    routed = action(cases, created, "transfer_case", actor=OPS, routing=routing, reason="routing restored")
    assert routed["response_due_at"] == "2026-11-12T04:00:00Z"
    assert routed["status"] == "queued" and routed["initial_queue_id"] is None


def test_transaction_failure_rolls_back_transfer_audit_and_outbox(work):
    claims, cases, routing, _, _, created, _ = work
    def fail(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO expense_case_outbox"):
            raise RuntimeError("outbox failed")
    event.listen(claims._engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="outbox failed"):
            action(cases, created, "transfer_case", routing=routing, reason="senior review", target_queue_id="finance_admin")
    finally:
        event.remove(claims._engine, "before_cursor_execute", fail)
    assert cases.get(created["case_id"], actor=OWNER) == created
    assert len(history(cases, created)) == 1
    with claims._engine.connect() as conn:
        assert conn.execute(select(cases._actions)).first() is None


def test_scan_permissions_cursor_stale_version_and_terminal_skip(work):
    claims, cases, routing, binding, _, created, now = work
    other_binding, _ = seed(claims)
    second = cases.create(**other_binding, actor=OWNER, routing=routing, request_id="second")
    error_code("queue_not_allowed", lambda: cases.scan_sla(actor=REVIEWER, routing=routing, request_id="denied"))
    error_code("invalid_handoff", lambda: cases.scan_sla(actor=ADMIN, routing=routing, request_id="bad", limit=0))
    page = cases.scan_sla(actor=ADMIN, routing=routing, request_id="p1", limit=1)
    assert page["next_cursor"] == min(created["case_id"], second["case_id"])
    assert cases.scan_sla(actor=ADMIN, routing=routing, request_id="p2", limit=1,
        after_case_id=page["next_cursor"])["next_cursor"] is None
    with claims._engine.begin() as conn:
        conn.execute(update(claims._claims).where(claims._claims.c.claim_id == binding["claim_id"]).values(current_version=2))
        conn.execute(update(cases._cases).where(cases._cases.c.case_id == second["case_id"]).values(status="cancelled"))
    now[0] += timedelta(days=2)
    scan = cases.scan_sla(actor=ADMIN, routing=routing, request_id="stale")
    assert scan == {"cases": [], "conflicts": [{"case_id": created["case_id"], "error_code": "claim_version_mismatch"}], "next_cursor": None}
    error_code("claim_version_mismatch", lambda: action(cases, created, routing=routing))
    assert len(history(cases, created)) == 1


def test_h1_legacy_rows_initialize_operational_state_lazily_without_history_rewrite(work):
    claims, cases, routing, _, _, created, _ = work
    original = history(cases, created)
    # Model a deployed H1 row with no H2 operational record.
    with claims._engine.begin() as conn:
        conn.execute(delete(cases._work))
    assert cases.get(created["case_id"], actor=OWNER) == created
    with claims._engine.connect() as conn:
        assert conn.execute(select(cases._work)).first() is None
    assert action(cases, created, routing=routing)["case_version"] == 2
    assert history(cases, created)[0] == original[0]


def test_late_claim_does_not_erase_response_sla_breach(work):
    _, cases, routing, _, _, created, now = work
    now[0] += timedelta(hours=5)
    action(cases, created, routing=routing)
    result = cases.scan_sla(actor=ADMIN, routing=routing, request_id="late")["cases"][0]
    assert result["response_breached"] and result["status"] == "assigned"
    assert not result["resolution_breached"]


def test_current_queue_unavailable_scan_unlocks_and_records_fail_closed_once(work):
    claims, cases, routing, binding, _, created, _ = work
    before = unchanged_business(claims, binding)
    action(cases, created, routing=routing)
    unavailable = replace(routing, queues=tuple(replace(q, available=False)
        if q.queue_id == "finance_review" else q for q in routing.queues))
    result = cases.scan_sla(actor=ADMIN, routing=unavailable, request_id="unavailable")["cases"][0]
    assert result["status"] == "unrouted" and result["assignee_id"] is None
    assert result["error_code"] == "queue_unavailable"
    assert cases.scan_sla(actor=ADMIN, routing=unavailable, request_id="repeat")["cases"] == []
    assert unchanged_business(claims, binding) == before


def test_expired_holder_can_release_or_another_member_can_reclaim_but_not_release(work):
    _, cases, routing, _, _, created, now = work
    claimed = action(cases, created, routing=routing)
    now[0] += timedelta(minutes=16)
    other = replace(REVIEWER, actor_id="other")
    error_code("case_not_claimable", lambda: action(cases, claimed, "release_case", actor=other,
        key="release-other", reason="expired"))
    assert len(history(cases, created)) == 2
    reclaimed = action(cases, claimed, actor=other, key="new-claim", routing=routing)
    assert reclaimed["assignee_id"] == other.actor_id
    now[0] += timedelta(minutes=16)
    released = action(cases, reclaimed, "release_case", actor=other, key="release-owned", reason="expired shift")
    assert released["status"] == "queued" and released["assignee_id"] is None
    assert [e["event_type"] for e in history(cases, created)].count("claim_lock_expired") == 2


def test_terminal_actions_and_invalid_versions_have_no_effect(work):
    claims, cases, routing, _, _, created, _ = work
    for version in (True, 0, "1"):
        error_code("case_version_conflict", lambda: action(cases, created, routing=routing, expected_case_version=version))
    with claims._engine.begin() as conn:
        conn.execute(update(cases._cases).where(cases._cases.c.case_id == created["case_id"]).values(status="cancelled"))
    error_code("invalid_case_transition", lambda: action(cases, created, routing=routing))
    assert len(history(cases, created)) == 1


def test_scan_failure_after_escalation_rolls_back_flags_events_queue_and_outbox(work):
    claims, cases, routing, _, _, created, now = work
    now[0] += timedelta(days=2)
    before_events = history(cases, created)
    before_outbox = cases.outbox(created["case_id"], actor=ADMIN)
    def fail(connection, cursor, statement, parameters, context, executemany):
        values = parameters.values() if isinstance(parameters, dict) else parameters
        if statement.startswith("INSERT INTO expense_case_events") and "sla_resolution_breached" in values:
            raise RuntimeError("breach marker write failed")
    event.listen(claims._engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="breach marker"):
            cases.scan_sla(actor=ADMIN, routing=routing, request_id="failure")
    finally:
        event.remove(claims._engine, "before_cursor_execute", fail)
    assert cases.get(created["case_id"], actor=OWNER) == created
    assert history(cases, created) == before_events
    assert cases.outbox(created["case_id"], actor=ADMIN) == before_outbox
    assert cases.scan_sla(actor=ADMIN, routing=routing, request_id="retry")["cases"][0]["resolution_breached"]


def test_self_referencing_escalation_route_is_unrouted_instead_of_scan_failure(work):
    claims, cases, routing, _, _, _, now = work
    config = replace(routing, queues=tuple(replace(q, escalate_to=q.queue_id)
        if q.queue_id == "finance_review" else q for q in routing.queues))
    binding, _ = seed(claims)
    created = cases.create(**binding, actor=OWNER, routing=config, request_id="self-route")
    now[0] += timedelta(days=2)
    result = next(c for c in cases.scan_sla(actor=ADMIN, routing=config, request_id="self-scan")["cases"]
        if c["case_id"] == created["case_id"])
    assert result["status"] == "unrouted" and result["error_code"] == "invalid_routing_config"
    assert result["resolution_breached"]
