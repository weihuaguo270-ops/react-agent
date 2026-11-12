"""H1 contracts on SQLite and, when configured, isolated PostgreSQL schemas."""
from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier

import pytest
from sqlalchemy import create_engine, delete, event, func, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from react_agent.apps.expense.case_store import CaseActor, ExpenseCaseStore
from react_agent.apps.expense.domain import Decision, Handoff
from react_agent.apps.expense.handoff import load_routing_config
from react_agent.apps.expense.store import ExpenseClaimStore, ExpenseStoreError

ROOT = Path(__file__).resolve().parents[3]
OWNER = CaseActor("employee-h1")
ADMIN = CaseActor("finance-admin-h1", "finance_admin")


@pytest.fixture(params=["sqlite", "postgresql"])
def storage(request, tmp_path):
    admin = None
    schema = None
    if request.param == "postgresql":
        url = os.environ.get("REACT_AGENT_TEST_POSTGRES_URL")
        if not url:
            pytest.skip("set REACT_AGENT_TEST_POSTGRES_URL to verify PostgreSQL contracts")
        admin = create_engine(url, pool_pre_ping=True)
        schema = "expense_h1_test_" + uuid.uuid4().hex
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(url, pool_pre_ping=True, connect_args={"options": f"-csearch_path={schema}"})
    else:
        engine = create_engine(f"sqlite:///{tmp_path / 'case.sqlite'}", connect_args={"timeout": 20})
        @event.listens_for(engine, "connect")
        def enable_foreign_keys(dbapi_connection, _):
            dbapi_connection.execute("PRAGMA foreign_keys=ON")
    try:
        claims = ExpenseClaimStore(engine=engine)
        cases = ExpenseCaseStore(claims)
        routing = load_routing_config(ROOT / "fixtures/expense/handoff_routing_v1.json")
        yield claims, cases, routing
    finally:
        engine.dispose()
        if admin is not None:
            with admin.begin() as connection:
                # Only this fixture's generated schema; never disable event triggers.
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin.dispose()


def seed(claims, *, owner=OWNER, reason="receipt_manual_verification", **changes):
    created = claims.create({
        "category": "meal", "amount": 128, "currency": "USD",
        "occurred_on": "2026-11-12", "description": "synthetic H1 contract",
        "has_receipt": True, "receipt_refs": ["receipt-h1"],
    }, actor_id=owner.actor_id, request_id="h1-create", idempotency_key=uuid.uuid4().hex)
    values = dict(
        decision="needs_review", reasons=("synthetic structured handoff",),
        decision_source="rules", decision_model="expense-h1-contract-v1", rule_result="matched",
        review_required=True, handoff=Handoff(reason, "medium", "100-500"),
        claim_id=created["claim_id"], claim_version=1, policy_version="expense-policy-sim-v1",
    )
    values.update(changes)
    decision = Decision(**values)
    submitted = claims.submit(created["claim_id"], actor_id=owner.actor_id, expected_version=1,
        request_id="h1-submit", idempotency_key=uuid.uuid4().hex,
        workflow_runner=lambda _: {"ok": True, "state": {"decision": decision.to_dict()}})
    return dict(claim_id=created["claim_id"], claim_version=1, decision_hash=decision.decision_hash), submitted


def create_case(storage):
    claims, cases, routing = storage
    binding, submitted = seed(claims)
    case = cases.create(**binding, actor=OWNER, routing=routing, request_id="h1-case")
    return binding, submitted, case


def test_create_reopen_case_events_and_pending_outbox_without_claim_mutation(storage):
    claims, cases, routing = storage
    binding, submitted = seed(claims)
    before = claims.get(binding["claim_id"], actor_id=OWNER.actor_id)
    audit_before = claims.events(binding["claim_id"], actor_id=OWNER.actor_id)
    created = cases.create(**binding, actor=OWNER, routing=routing, request_id="h1-case")
    assert created["approval_id"] is None
    assert (created["status"], created["queue_id"]) == ("queued", "finance_review")
    assert created["sla"]["sla_policy_version"] == "expense-sla-v1"
    assert created["idempotent_replay"] is False
    evidence = cases.append_event(created["case_id"], actor=OWNER, request_id="h1-evidence",
        idempotency_key="receipt-add", evidence_ref="receipt-h1:verified")
    claims._engine.dispose()
    reopened = ExpenseCaseStore(ExpenseClaimStore(engine=claims._engine))
    assert reopened.get(created["case_id"], actor=OWNER) == created
    events = reopened.events(created["case_id"], actor=OWNER)
    assert [e["event_type"] for e in events] == ["case_created", "evidence_recorded"]
    assert [e["sequence"] for e in events] == [1, 2]
    assert events[1] == evidence
    assert events[0]["from_status"] is None and events[0]["to_status"] == "queued"
    assert events[1]["from_status"] == events[1]["to_status"] == "queued"
    for row in events:
        assert set(row) >= {"event_id", "case_id", "event_type", "actor_type", "actor_id",
            "queue_id", "claim_version", "request_id", "created_at", "metadata", "from_status", "to_status"}
        assert row["created_at"].endswith("Z")
    pending = reopened.outbox(created["case_id"], actor=ADMIN)
    assert len(pending) == 1 and pending[0]["status"] == "pending"
    assert pending[0]["event_id"] == events[0]["event_id"]
    assert pending[0]["payload"] == {"case_id": created["case_id"], "event_id": events[0]["event_id"]}
    assert claims.get(binding["claim_id"], actor_id=OWNER.actor_id) == before
    assert claims.events(binding["claim_id"], actor_id=OWNER.actor_id) == audit_before
    assert len(claims.list_reviews(claim_id=binding["claim_id"])) == 1
    assert claims.list_reviews(claim_id=binding["claim_id"])[0]["approval_status"] == "pending"


def test_duplicate_create_preserves_original_case_route_sla_and_outbox(storage):
    _, cases, routing = storage
    binding, _, created = create_case(storage)
    changed = replace(routing, routing_rule_version="routing-v2", rules=())
    replay = cases.create(**binding, actor=OWNER, routing=changed, request_id="h1-retry")
    assert replay == {**created, "idempotent_replay": True}
    assert len(cases.events(created["case_id"], actor=OWNER)) == 1
    assert len(cases.outbox(created["case_id"], actor=ADMIN)) == 1


def test_parallel_creation_has_one_case_one_event_one_outbox(storage):
    claims, cases, routing = storage
    binding, _ = seed(claims)
    barrier = Barrier(4)
    def attempt(i):
        barrier.wait(timeout=10)
        return cases.create(**binding, actor=OWNER, routing=routing, request_id=f"parallel-{i}")
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(attempt, range(4)))
    assert len({r["case_id"] for r in results}) == 1
    assert sum(not r["idempotent_replay"] for r in results) == 1
    assert len(cases.events(results[0]["case_id"], actor=OWNER)) == 1
    assert len(cases.outbox(results[0]["case_id"], actor=ADMIN)) == 1
    with claims._engine.connect() as connection:
        row = dict(connection.execute(select(cases._cases)).mappings().one())
    row["case_id"] = "case-duplicate-raw"
    with pytest.raises(IntegrityError):
        with claims._engine.begin() as connection:
            connection.execute(cases._cases.insert().values(**row))


def test_failure_after_event_rolls_back_all_three_tables(storage):
    claims, cases, routing = storage
    binding, _ = seed(claims)
    def fail_outbox(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO expense_case_outbox"):
            raise RuntimeError("simulated outbox persistence failure")
    event.listen(claims._engine, "before_cursor_execute", fail_outbox)
    try:
        with pytest.raises(RuntimeError, match="outbox persistence"):
            cases.create(**binding, actor=OWNER, routing=routing, request_id="rollback")
    finally:
        event.remove(claims._engine, "before_cursor_execute", fail_outbox)
    with claims._engine.connect() as connection:
        for table in (cases._cases, cases._events, cases._outbox):
            assert connection.execute(select(func.count()).select_from(table)).scalar_one() == 0
    assert cases.create(**binding, actor=OWNER, routing=routing, request_id="retry")["idempotent_replay"] is False


@pytest.mark.parametrize("mutation", ["update", "delete", "truncate"])
def test_event_history_rejects_direct_sql_mutation(storage, mutation):
    claims, cases, _ = storage
    _, _, created = create_case(storage)
    original = cases.events(created["case_id"], actor=OWNER)
    if mutation == "truncate" and claims._engine.dialect.name == "sqlite":
        pytest.skip("SQLite has no TRUNCATE statement")
    statement = {
        "update": update(cases._events).values(metadata_json='{}'),
        "delete": delete(cases._events),
        "truncate": text("TRUNCATE expense_case_events CASCADE"),
    }[mutation]
    with pytest.raises(DBAPIError, match="append-only"):
        with claims._engine.begin() as connection:
            connection.execute(statement)
    assert cases.events(created["case_id"], actor=OWNER) == original


def test_append_is_ordered_idempotent_and_keeps_status(storage):
    _, cases, _ = storage
    _, _, created = create_case(storage)
    args = dict(actor=OWNER, request_id="evidence-1", idempotency_key="e1", evidence_ref="receipt:one")
    first = cases.append_event(created["case_id"], **args)
    replay = cases.append_event(created["case_id"], **{**args, "request_id": "retry"})
    assert replay == {**first, "idempotent_replay": True}
    with pytest.raises(ExpenseStoreError) as error:
        cases.append_event(created["case_id"], **{**args, "evidence_ref": "different"})
    assert error.value.code == "idempotency_conflict"
    with pytest.raises(ExpenseStoreError):
        cases.append_event(created["case_id"], **{**args, "evidence_ref": "password=secret"})
    assert len(cases.events(created["case_id"], actor=OWNER)) == 2
    assert cases.get(created["case_id"], actor=OWNER)["status"] == "queued"


@pytest.mark.parametrize("same_key", [False, True])
def test_concurrent_append_serializes_sequence_and_reuses_event_keys(storage, same_key):
    _, cases, _ = storage
    _, _, created = create_case(storage)
    barrier = Barrier(4)
    def append(i):
        barrier.wait(timeout=10)
        key = "shared" if same_key else f"evidence-{i}"
        return cases.append_event(created["case_id"], actor=OWNER, request_id=f"parallel-{i}",
            idempotency_key=key, evidence_ref="receipt:same")
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(append, range(4)))
    count = 1 if same_key else 4
    assert len({r["event_id"] for r in results}) == count
    assert sum(not r["idempotent_replay"] for r in results) == count
    assert [e["sequence"] for e in cases.events(created["case_id"], actor=OWNER)] == list(range(1, count + 2))
    assert len(cases.outbox(created["case_id"], actor=ADMIN)) == 1


def test_unauthorized_reads_creation_and_events_hide_existence(storage):
    _, cases, routing = storage
    binding, _, created = create_case(storage)
    outsider = CaseActor("other-employee")
    for actor in (outsider, CaseActor("reviewer", "finance_reviewer"),
                  CaseActor("reviewer", "finance_reviewer", ("finance_admin",)),
                  CaseActor("operator", "expense_operator", ("expense_operations",))):
        for operation in (cases.get, cases.events, cases.outbox):
            for case_id in (created["case_id"], "case-absent"):
                with pytest.raises(ExpenseStoreError) as error:
                    operation(case_id, actor=actor)
                assert (error.value.code, error.value.status_code, str(error.value)) == ("case_not_found", 404, "expense case not found")
        assert cases.list_cases(actor=actor) == []
    with pytest.raises(ExpenseStoreError) as error:
        cases.create(**binding, actor=outsider, routing=routing, request_id="stolen-replay")
    assert error.value.code == "case_not_found"
    with pytest.raises(ExpenseStoreError):
        cases.append_event(created["case_id"], actor=outsider, request_id="bad", idempotency_key="bad", evidence_ref="r1")
    with pytest.raises(ExpenseStoreError):
        cases.outbox(created["case_id"], actor=OWNER)
    reviewer = CaseActor("queue-reviewer", "finance_reviewer", ("finance_review",))
    assert cases.get(created["case_id"], actor=reviewer)["case_id"] == created["case_id"]
    assert len(cases.outbox(created["case_id"], actor=reviewer)) == 1
    assert len(cases.list_cases(actor=OWNER)) == len(cases.list_cases(actor=ADMIN)) == len(cases.list_cases(actor=reviewer)) == 1


def test_optional_approval_must_match_existing_claim_version_and_decision(storage):
    claims, cases, routing = storage
    binding, submitted = seed(claims)
    _, other = seed(claims)
    for approval_id in ("approval-absent", other["approval_id"]):
        with pytest.raises(ExpenseStoreError) as error:
            cases.create(**binding, actor=OWNER, routing=routing, request_id="bad-binding", approval_id=approval_id)
        assert error.value.code == "approval_binding_mismatch"
    created = cases.create(**binding, actor=OWNER, routing=routing, request_id="bound", approval_id=submitted["approval_id"])
    assert created["approval_id"] == submitted["approval_id"]
    with pytest.raises(ExpenseStoreError) as error:
        cases.create(**binding, actor=OWNER, routing=routing, request_id="change-binding")
    assert error.value.code == "idempotency_conflict"
    assert claims.get(binding["claim_id"], actor_id=OWNER.actor_id)["status"] == "under_review"


def test_unrouted_persists_pending_ops_intent_without_assignment(storage):
    claims, cases, routing = storage
    binding, _ = seed(claims)
    created = cases.create(**binding, actor=OWNER, routing=replace(routing, rules=()), request_id="unrouted")
    assert created["status"] == "unrouted" and created["queue_id"] is None
    ops = CaseActor("ops", "expense_operator", ("expense_operations",))
    assert cases.get(created["case_id"], actor=ops)["case_id"] == created["case_id"]
    assert cases.outbox(created["case_id"], actor=ops)[0]["notification_type"] == "case_unrouted"
    assert cases.outbox(created["case_id"], actor=ops)[0]["target_queue"] == "expense_operations"


@pytest.mark.parametrize("field,value", [("claim_version", 2), ("decision_hash", "sha256:other")])
def test_existing_approval_with_stale_binding_cannot_be_attached(storage, field, value):
    claims, cases, routing = storage
    binding, submitted = seed(claims)
    with claims._engine.begin() as connection:
        connection.execute(update(claims._reviews).where(
            claims._reviews.c.approval_id == submitted["approval_id"]).values(**{field: value}))
    with pytest.raises(ExpenseStoreError) as error:
        cases.create(**binding, actor=OWNER, routing=routing, request_id="stale-approval",
            approval_id=submitted["approval_id"])
    assert error.value.code == "approval_binding_mismatch"
    assert cases.list_cases(actor=OWNER) == []


def test_draft_without_persisted_decision_cannot_create_case(storage):
    claims, cases, routing = storage
    draft = claims.create({"category": "meal", "amount": 128, "currency": "USD",
        "occurred_on": "2026-11-12", "description": "synthetic draft", "has_receipt": True},
        actor_id=OWNER.actor_id, request_id="draft", idempotency_key="draft")
    with pytest.raises(ExpenseStoreError) as error:
        cases.create(draft["claim_id"], claim_version=1, decision_hash="sha256:absent",
            actor=OWNER, routing=routing, request_id="draft-case")
    assert error.value.code == "invalid_handoff"
    assert cases.list_cases(actor=OWNER) == []


@pytest.mark.parametrize("change,code", [("version", "claim_version_mismatch"), ("hash", "idempotency_conflict")])
def test_version_and_hash_conflicts_write_nothing(storage, change, code):
    claims, cases, routing = storage
    binding, _ = seed(claims)
    invalid = {**binding, **({"claim_version": 2} if change == "version" else {"decision_hash": "sha256:wrong"})}
    with pytest.raises(ExpenseStoreError) as error:
        cases.create(**invalid, actor=OWNER, routing=routing, request_id="invalid")
    assert error.value.code == code
    assert cases.list_cases(actor=OWNER) == []


@pytest.mark.parametrize("reason,changes", [
    ("free text legacy reason", {}),
    ("approval_record_required", {"decision": "approve_manager", "review_required": False}),
    ("approval_record_required", {"decision": "reject_policy", "review_required": False, "rule_result": "rejected"}),
])
def test_compatibility_reasons_and_non_handoff_decisions_fail_closed(storage, reason, changes):
    claims, cases, routing = storage
    binding, _ = seed(claims, reason=reason, **changes)
    with pytest.raises(ExpenseStoreError) as error:
        cases.create(**binding, actor=OWNER, routing=routing, request_id="non-handoff")
    assert error.value.code == "invalid_handoff"
    assert cases.list_cases(actor=OWNER) == []
