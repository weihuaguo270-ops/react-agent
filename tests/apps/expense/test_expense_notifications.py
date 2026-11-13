"""H4 retry/crash/metrics contracts on H1's SQLite and isolated PostgreSQL setup."""
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from threading import Barrier

import pytest
from sqlalchemy import event, func, select

from react_agent.apps.expense.case_metrics import rebuild_metrics
from react_agent.apps.expense.case_store import ExpenseCaseStore
from react_agent.apps.expense.notifications import DeliveryResult, LocalNotificationAdapter, OutboxWorker
from react_agent.apps.expense.store import ExpenseClaimStore
from .test_expense_case_operations import (
    REVIEWER, action, error_code, history, unchanged_business, work,  # noqa: F401
)
from .test_expense_case_store import ADMIN, OWNER, seed, storage  # noqa: F401


class RecordingAdapter:
    local_only = True

    def __init__(self, result=DeliveryResult("local-test", "accepted", None)):
        self.result = result
        self.calls = []

    def deliver(self, notification):
        self.calls.append(notification)
        return self.result


def statuses(cases, created):
    return cases.delivery_status(created["case_id"], actor=ADMIN)


def test_failure_survives_reopen_then_retries_without_business_changes(work):
    claims, cases, _, binding, _, created, now = work
    before = unchanged_business(claims, binding)
    case_before = cases.get(created["case_id"], actor=ADMIN)
    original_intents = cases.outbox(created["case_id"], actor=ADMIN)
    metrics_before = cases.metrics(actor=ADMIN)
    adapter = RecordingAdapter(DeliveryResult(None, "failed", "local_unavailable"))
    worker = OutboxWorker(cases, adapter, actor=ADMIN, retry_base_seconds=5, retry_max_seconds=8)
    result = worker.run_once()
    assert result[0]["error"] == "local_unavailable" and result[0]["recorded"]
    assert statuses(cases, created)[0]["status"] == "retry_wait"
    assert worker.run_once() == []
    now[0] += timedelta(seconds=5)
    assert worker.run_once()[0]["status"] == "failed"
    assert statuses(cases, created)[0]["next_attempt_at"].endswith("00:00:13Z")
    claims._engine.dispose()
    reopened = ExpenseCaseStore(ExpenseClaimStore(engine=claims._engine), clock=lambda: now[0])
    assert statuses(reopened, created) == statuses(cases, created)
    now[0] += timedelta(seconds=8)
    adapter = LocalNotificationAdapter(reopened)
    worker = OutboxWorker(reopened, adapter, actor=ADMIN)
    assert worker.run_once()[0]["status"] == "accepted"
    assert worker.run_once() == []
    receipt = statuses(reopened, created)[0]
    assert receipt["attempt"] == 3 and receipt["delivery_id"].startswith("local_")
    assert receipt["user_read"] is False and receipt["next_attempt_at"] is None
    assert cases.outbox(created["case_id"], actor=ADMIN) == original_intents
    assert cases.get(created["case_id"], actor=ADMIN) == case_before
    assert unchanged_business(claims, binding) == before
    assert cases.metrics(actor=ADMIN) == metrics_before
    assert len([e for e in history(cases, created) if e["event_type"] == "notification_attempt_finished"]) == 3


def test_concurrent_workers_only_one_live_lease(work):
    _, cases, _, _, _, created, _ = work
    barrier = Barrier(4)
    adapter = RecordingAdapter()
    def run(_):
        barrier.wait(timeout=10)
        return OutboxWorker(cases, adapter, actor=ADMIN).run_once()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, range(4)))
    assert sum(len(r) for r in results) == 1
    assert len(adapter.calls) == 1
    assert statuses(cases, created)[0]["attempt"] == 1


def test_additive_h4_tables_consume_existing_pending_intents(work):
    claims, cases, _, _, _, created, now = work
    original = cases.outbox(created["case_id"], actor=ADMIN)
    audit = history(cases, created)
    # Model an existing H3 schema: retain all business tables/events/outbox,
    # remove only the new, still-empty H4 tables, then attach a new store.
    cases._local_receipts.drop(claims._engine)
    cases._deliveries.drop(claims._engine)
    reopened = ExpenseCaseStore(ExpenseClaimStore(engine=claims._engine), clock=lambda: now[0])
    assert history(reopened, created) == audit
    assert OutboxWorker(reopened, LocalNotificationAdapter(reopened), actor=ADMIN).run_once()[0]["status"] == "accepted"
    assert reopened.outbox(created["case_id"], actor=ADMIN) == original


def test_crash_after_adapter_acceptance_reclaims_with_stable_id_and_fences_stale_ack(work):
    claims, cases, _, binding, _, created, now = work
    before = unchanged_business(claims, binding)
    intent = cases.outbox(created["case_id"], actor=ADMIN)[0]
    reserved, token, attempt = cases._reserve_notification(intent["outbox_id"], actor=ADMIN, lease_seconds=10)
    with cases._engine.connect() as connection:
        notification = cases._notification(connection, reserved)
    accepted = LocalNotificationAdapter(cases).deliver(notification)
    assert OutboxWorker(cases, RecordingAdapter(), actor=ADMIN).run_once() == []
    now[0] += timedelta(seconds=11)
    assert not cases._finish_notification(intent, token, attempt, accepted, actor=ADMIN, retry_seconds=5)
    claims._engine.dispose()
    reopened = ExpenseCaseStore(ExpenseClaimStore(engine=claims._engine), clock=lambda: now[0])
    assert OutboxWorker(reopened, LocalNotificationAdapter(reopened), actor=ADMIN).run_once()[0]["delivery_id"] == accepted.delivery_id
    assert not cases._finish_notification(intent, token, attempt, DeliveryResult(None, "failed", "late"),
        actor=ADMIN, retry_seconds=5)
    assert statuses(reopened, created)[0]["status"] == "accepted"
    assert statuses(reopened, created)[0]["attempt"] == 2
    with claims._engine.connect() as connection:
        assert connection.execute(select(func.count()).select_from(cases._local_receipts)).scalar_one() == 1
    assert [e["event_type"] for e in history(cases, created)].count("notification_lease_expired") == 1
    assert unchanged_business(claims, binding) == before


@pytest.mark.parametrize("bad", ["exception", {}, DeliveryResult("x", "read", None),
    DeliveryResult(None, "failed", "password=secret")])
def test_adapter_failure_is_redacted_and_retryable(work, bad):
    _, cases, _, _, _, created, _ = work
    class Adapter(RecordingAdapter):
        def deliver(self, notification):
            if bad == "exception":
                raise RuntimeError("password=secret")
            return bad
    OutboxWorker(cases, Adapter(), actor=ADMIN).run_once()
    assert statuses(cases, created)[0]["status"] == "retry_wait"
    assert statuses(cases, created)[0]["error"] in {"adapter_exception", "adapter_invalid_result"}
    assert "password" not in json.dumps(history(cases, created))


def test_result_and_audit_commit_together_even_on_notification_failure(work):
    _, cases, _, _, _, created, now = work
    def fail_result(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("UPDATE expense_notification_delivery"):
            raise RuntimeError("result commit failed")
    event.listen(cases._engine, "before_cursor_execute", fail_result)
    try:
        with pytest.raises(RuntimeError, match="commit failed"):
            OutboxWorker(cases, LocalNotificationAdapter(cases), actor=ADMIN, lease_seconds=10).run_once()
    finally:
        event.remove(cases._engine, "before_cursor_execute", fail_result)
    assert statuses(cases, created)[0]["status"] == "processing"
    assert not any(e["event_type"] == "notification_attempt_finished" for e in history(cases, created))
    now[0] += timedelta(seconds=11)
    assert OutboxWorker(cases, LocalNotificationAdapter(cases), actor=ADMIN).run_once()[0]["status"] == "accepted"


def test_notification_intents_snapshot_targets_and_never_resume_waiting(work):
    claims, cases, routing, binding, _, created, now = work
    assigned = action(cases, created, routing=routing)
    started = action(cases, assigned, "start_case", key="start")
    waiting = action(cases, started, "request_applicant", key="wait", reason="need receipt")
    before = unchanged_business(claims, binding)
    adapter = RecordingAdapter()
    OutboxWorker(cases, adapter, actor=ADMIN).run_once()
    sent = {n.notification_type: n for n in adapter.calls}
    assert sent["case_created"].recipients == ("queue:finance_review",)
    assert sent["case_assigned"].recipients == ("actor:reviewer",)
    assert sent["needs_applicant"].recipients == ("actor:" + OWNER.actor_id,)
    now[0] += timedelta(days=2)
    cases.scan_sla(actor=ADMIN, routing=routing, request_id="scan", warning_before_seconds=300)
    assert cases.get(created["case_id"], actor=ADMIN) == waiting
    assert unchanged_business(claims, binding) == before


def test_sla_warning_breach_intents_and_audit_metrics_are_idempotent(work):
    claims, cases, routing, binding, _, created, now = work
    before = unchanged_business(claims, binding)
    now[0] += timedelta(hours=4, seconds=-60)
    cases.scan_sla(actor=ADMIN, routing=routing, request_id="warning", warning_before_seconds=120)
    warning_events = history(cases, created)
    cases.scan_sla(actor=ADMIN, routing=routing, request_id="again", warning_before_seconds=120)
    assert history(cases, created) == warning_events
    now[0] += timedelta(seconds=60)
    cases.scan_sla(actor=ADMIN, routing=routing, request_id="breach")
    now[0] += timedelta(hours=20)
    cases.scan_sla(actor=ADMIN, routing=routing, request_id="resolution")
    adapter = RecordingAdapter()
    OutboxWorker(cases, adapter, actor=ADMIN).run_once()
    assert sum(n.notification_type == "sla_warning" for n in adapter.calls) == 1
    assert sum(n.notification_type == "sla_breached" for n in adapter.calls) == 2
    assert all(n.recipients[0].startswith("queue_owner:") for n in adapter.calls if n.notification_type.startswith("sla_"))
    audit = cases.metrics_audit(actor=ADMIN)
    rebuilt = rebuild_metrics(json.loads(json.dumps(audit)))
    assert rebuilt == cases.metrics(actor=ADMIN)
    assert rebuilt["pending"] == 1
    assert rebuilt["queues"]["finance_admin"]["by_status"] == {"escalated": 1}
    assert rebuilt["sla_breach"] == {"cases": 1, "response": 1, "resolution": 1, "basis": "recorded_scan_events"}
    assert rebuilt["human_handoff"]["rate"] == 1.0
    assert unchanged_business(claims, binding) == before


def test_resolution_delivery_failure_cannot_change_approved_claim(work, monkeypatch):
    claims, cases, routing, binding, submitted, created, _ = work
    monkeypatch.setenv("REACT_AGENT_APPROVAL_MODE", "auto_allow")
    assigned = action(cases, created, routing=routing)
    started = action(cases, assigned, "start_case", key="start")
    resolved = cases.resolve_case(started["case_id"], actor=REVIEWER,
        expected_case_version=started["case_version"], request_id="resolve", idempotency_key="resolve",
        decision="approve", approval_id=submitted["approval_id"], claim_version=1,
        decision_hash=binding["decision_hash"], reason="synthetic checked")
    before = unchanged_business(claims, binding)
    assert before[0]["status"] == "approved"
    adapter = RecordingAdapter(DeliveryResult(None, "failed", "local_down"))
    OutboxWorker(cases, adapter, actor=ADMIN).run_once()
    notice = next(n for n in adapter.calls if n.notification_type == "case_resolved")
    assert notice.recipients == ("actor:" + OWNER.actor_id, "observers:finance_review")
    assert cases.get(created["case_id"], actor=ADMIN) == resolved
    assert unchanged_business(claims, binding) == before
    assert cases.metrics(actor=ADMIN)["pending"] == 0


def test_admin_worker_and_metrics_authorization_and_local_only_boundary(work):
    _, cases, _, _, _, created, _ = work
    for actor in (OWNER, REVIEWER):
        error_code("queue_not_allowed", lambda: OutboxWorker(cases, RecordingAdapter(), actor=actor))
        error_code("queue_not_allowed", lambda: cases.metrics_audit(actor=actor))
    error_code("case_not_found", lambda: cases.delivery_status(created["case_id"], actor=OWNER))
    adapter = RecordingAdapter()
    adapter.local_only = False
    with pytest.raises(ValueError, match="local"):
        OutboxWorker(cases, adapter, actor=ADMIN)
    assert len(history(cases, created)) == 1


def test_metrics_denominator_is_submitted_versions_and_missing_legacy_link_is_unavailable(work):
    claims, cases, routing, _, _, created, _ = work
    seed(claims)  # A second submitted Claim has no case.
    audit = cases.metrics_audit(actor=ADMIN)
    # Export can be replayed in any order with duplicate batches.
    duplicated = deepcopy(audit)
    duplicated["case_events"] = list(reversed(audit["case_events"])) * 2
    duplicated["claim_events"] *= 2
    assert rebuild_metrics(duplicated) == cases.metrics(actor=ADMIN)
    assert rebuild_metrics(audit)["human_handoff"]["rate"] == 0.5
    # Projection must use audit queue/status, even when live rows change later.
    action(cases, created, routing=routing)
    assert rebuild_metrics(audit)["queues"]["finance_review"]["by_status"] == {"queued": 1}
    assert cases.metrics(actor=ADMIN)["queues"]["finance_review"]["by_status"] == {"assigned": 1}
    audit["case_events"][0]["metadata"].pop("claim_id")
    assert rebuild_metrics(audit)["human_handoff"]["unattributed_cases"] == 1
    assert rebuild_metrics(audit)["human_handoff"]["rate"] is None
    assert rebuild_metrics(audit)["human_handoff"]["status"] == "unavailable"


def test_metrics_distinct_claim_version_not_case_count():
    event = dict(case_id="one", event_id="e1", event_type="case_created", sequence=1,
        queue_id="finance_review", to_status="queued", claim_version=1, metadata={"claim_id": "claim"})
    audit = {"case_events": [event, {**event, "case_id": "two", "event_id": "e2"}],
        "claim_events": [dict(event_type="claim_submitted", claim_id="claim", claim_version=1)]}
    assert rebuild_metrics(audit)["human_handoff"]["rate"] == 1.0
    assert rebuild_metrics(audit)["total_cases"] == 2
    audit["claim_events"] = []
    assert rebuild_metrics(audit)["human_handoff"]["missing_submission_versions"] == 1
    assert rebuild_metrics(audit)["human_handoff"]["rate"] is None
