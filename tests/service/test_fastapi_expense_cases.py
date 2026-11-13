"""S6 HTTP handoff smoke: real SQL/HTTP/gate; controlled Decision is synthetic."""
from __future__ import annotations

import asyncio
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import httpx
import pytest
from sqlalchemy import event, func, select, update

pytest.importorskip("fastapi")

from react_agent.apps.expense.domain import Decision, Handoff
from react_agent.apps.expense.review import route_review
from react_agent.apps.expense.store import ExpenseStoreError
from tests.apps.expense.test_expense_case_store import OWNER, seed, storage  # noqa: F401

BASE = "/v1/expense"


class HTTP:
    def __init__(self, app):
        self.app = app

    def request(self, method, path, *, actor=OWNER.actor_id, key=None, **kwargs):
        headers = {"Authorization": "Bearer synthetic-s6-token", "X-Actor-Id": actor,
            "Idempotency-Key": key or uuid.uuid4().hex, **kwargs.pop("headers", {})}
        async def call():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),
                    base_url="http://127.0.0.1") as client:
                return await client.request(method, BASE + path, headers=headers, **kwargs)
        return asyncio.run(call())

    def submit(self):
        created = self.request("POST", "/claims", json={"category": "meal", "amount": 128,
            "currency": "USD", "occurred_on": "2026-11-13", "description": "synthetic HTTP handoff",
            "has_receipt": True, "receipt_refs": ["receipt-s6"]})
        assert created.status_code == 201, created.text
        claim_id = created.json()["claim_id"]
        response = self.request("POST", f"/claims/{claim_id}/submit", key="submit-" + claim_id,
            json={"expected_version": 1})
        assert response.status_code == 200, response.text
        return response.json()

    def action(self, case, name, *, actor="reviewer-s6", **payload):
        response = self.request("POST", f"/cases/{case['case_id']}/{name}", actor=actor,
            json={"expected_case_version": case["case_version"], **payload})
        assert response.status_code == 200, response.text
        return response.json()["case"]


@pytest.fixture
def http(storage, monkeypatch, tmp_path):
    from react_agent.apps.expense import service
    from react_agent.server import fastapi_app

    claims, cases, routing = storage
    claims.enable_handoff(routing)
    directory = tmp_path / "actors.json"
    directory.write_text(json.dumps({
        "reviewer-s6": {"role": "finance_reviewer", "queue_ids": ["finance_review"]},
        "reviewer-other": {"role": "finance_reviewer", "queue_ids": ["finance_review"]},
        "admin-s6": {"role": "finance_admin", "queue_ids": ["finance_review", "finance_admin"]},
        "operator-s6": {"role": "expense_operator", "queue_ids": ["expense_operations"]},
    }), encoding="utf-8")
    monkeypatch.setenv("REACT_AGENT_EXPENSE_CASE_ACTORS_FILE", str(directory))
    monkeypatch.setenv("REACT_AGENT_AUTH_TOKEN", "synthetic-s6-token")
    monkeypatch.setenv("REACT_AGENT_PERMISSION_GATE", "1")
    monkeypatch.setenv("REACT_AGENT_APPROVAL_MODE", "auto_allow")
    monkeypatch.setenv("REACT_AGENT_APPROVAL_DIR", str(tmp_path / "approvals"))
    monkeypatch.delenv("REACT_AGENT_STRICT_CONFIRM", raising=False)
    monkeypatch.delenv("REACT_AGENT_SANDBOX_REQUIRED", raising=False)
    monkeypatch.setattr(fastapi_app, "_expense_store", lambda: claims)

    def controlled(claim, **kwargs):
        decision = Decision(decision="needs_review", reasons=("synthetic controlled receipt check",),
            decision_source="rules", decision_model="s6-http-smoke-v1", rule_result="matched",
            review_required=True, handoff=Handoff("receipt_manual_verification", "medium", "100-500"),
            claim_id=claim["claim_id"], claim_version=claim["version"], policy_version="expense-policy-sim-v1")
        return {"ok": True, "state": {"decision": decision.to_dict()}, "run_id": "s6-synthetic"}

    client = HTTP(fastapi_app.create_app(initialize_runtime=False))
    client.real_workflow = service._run_submit_workflow
    monkeypatch.setattr(service, "_run_submit_workflow", controlled)
    return client, claims, cases, routing


def binding(submitted):
    return {"claim_id": submitted["claim_id"], "claim_version": submitted["version"],
        "decision_hash": submitted["decision"]["decision_hash"]}


def resolve_body(submitted, case, **changes):
    return {"decision": "approve", "approval_id": submitted["approval_id"],
        "claim_version": submitted["version"], "decision_hash": submitted["decision"]["decision_hash"],
        "expected_case_version": case["case_version"], "reason": "verified synthetic receipt", **changes}


def business(claims, submitted):
    return (claims.get(submitted["claim_id"], actor_id=OWNER.actor_id),
        claims.list_reviews(claim_id=submitted["claim_id"]),
        claims.events(submitted["claim_id"], actor_id=OWNER.actor_id))


def test_http_submit_repeat_handoff_queue_hint_and_scoped_summary(http):
    client, claims, cases, routing = http
    submitted = client.submit()
    case = submitted["handoff"]
    assert case["approval_id"] == submitted["approval_id"]
    assert case["status"] == "queued" and case["queue_id"] == "finance_review"
    assert case["decision_hash"] == submitted["decision"]["decision_hash"]
    repeated = client.request("POST", f"/claims/{submitted['claim_id']}/submit",
        key="submit-" + submitted["claim_id"], json={"expected_version": 1})
    assert repeated.json()["case_id"] == case["case_id"]
    for _ in range(2):
        response = client.request("POST", "/cases", key="repeat-handoff",
            json={**binding(submitted), "suggested_queue": "nonexistent-admin-queue"})
        assert response.status_code == 200, response.text
        assert response.json()["case"]["case_id"] == case["case_id"]
        assert response.json()["case"]["queue_id"] == "finance_review"
    assert len(cases.events(case["case_id"], actor=OWNER)) == 1
    response = client.request("POST", "/cases", key="repeat-handoff",
        json={**binding(submitted), "suggested_queue": "different"})
    assert response.status_code == 409 and response.json()["error"]["code"] == "idempotency_conflict"
    assert client.request("GET", "/queues").json()["queues"] == []
    queues = client.request("GET", "/queues", actor="reviewer-s6").json()["queues"]
    assert [q["queue_id"] for q in queues] == ["finance_review"]
    assert queues[0]["summary"]["pending"] == 1
    assert client.request("GET", "/cases", actor="outsider").json()["cases"] == []


def test_route_review_backfills_controlled_handoff_atomically(storage):
    claims, cases, routing = storage
    bound, submitted = seed(claims)
    cases = claims.enable_handoff(routing)
    claim = claims.get(bound["claim_id"], actor_id=OWNER.actor_id)["claim"]
    claim.update(expense_type="business_meal", participants=[OWNER.actor_id])
    result = route_review(claim, submitted["decision"], store=claims,
        request_id="s6-route", idempotency_key="s6-route")
    replay = route_review(claim, submitted["decision"], store=claims,
        request_id="s6-repeat-route", idempotency_key="s6-route-again")
    assert result["case_id"] == replay["case_id"]
    assert result["decision"]["decision_hash"] == bound["decision_hash"]
    assert len(cases.events(result["case_id"], actor=OWNER)) == 1


def test_http_concurrent_claim_and_escalation_do_not_approve(http):
    client, claims, cases, _ = http
    submitted = client.submit()
    case = submitted["handoff"]
    barrier = Barrier(2)
    def claim(actor):
        barrier.wait(timeout=10)
        return client.request("POST", f"/cases/{case['case_id']}/claim", actor=actor,
            json={"expected_case_version": case["case_version"]})
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(claim, ("reviewer-s6", "reviewer-other")))
    assert sorted(r.status_code for r in responses) == [200, 409]
    loser = next(r for r in responses if r.status_code != 200)
    assert loser.json()["error"]["code"] == "case_already_claimed"
    assigned = next(r.json()["case"] for r in responses if r.status_code == 200)
    before = business(claims, submitted)
    escalated = client.action(assigned, "escalate", actor=assigned["assignee_id"], reason="needs senior review")
    assert escalated["status"] == "escalated" and escalated["queue_id"] == "finance_admin"
    assert escalated["assignee_id"] is None
    assert business(claims, submitted) == before
    events = client.request("GET", f"/cases/{case['case_id']}/events").json()["events"]
    assert events[-1]["metadata"]["from_queue"] == "finance_review"
    assert events[-1]["metadata"]["to_queue"] == "finance_admin"


@pytest.mark.parametrize("decision,status", [("approve", "approved"), ("reject", "rejected")])
def test_http_resolve_uses_legal_approval_and_rejects_replay(http, decision, status):
    client, claims, cases, _ = http
    submitted = client.submit()
    started = client.action(client.action(submitted["handoff"], "claim"), "start")
    response = client.request("POST", f"/cases/{started['case_id']}/resolve", actor="reviewer-s6",
        json=resolve_body(submitted, started, decision=decision))
    assert response.status_code == 200, response.text
    assert response.json()["case"]["status"] == "resolved"
    assert claims.get(submitted["claim_id"], actor_id=OWNER.actor_id)["status"] == status
    review = claims.list_reviews(claim_id=submitted["claim_id"])[0]
    assert review["resolution"]["approver_id"] == "reviewer-s6"
    repeated = client.request("POST", f"/cases/{started['case_id']}/resolve", actor="reviewer-s6",
        json=resolve_body(submitted, started, decision=decision))
    assert repeated.status_code == 409


@pytest.mark.parametrize("change", [
    {"approval_id": None}, {"approval_id": "missing"}, {"claim_version": 2},
    {"decision_hash": "sha256:" + "0" * 64}, {"expected_case_version": 99},
])
def test_http_invalid_resolution_binding_has_no_side_effects(http, change):
    client, claims, cases, _ = http
    submitted = client.submit()
    started = client.action(client.action(submitted["handoff"], "claim"), "start")
    before = business(claims, submitted), cases.events(started["case_id"], actor=OWNER)
    response = client.request("POST", f"/cases/{started['case_id']}/resolve", actor="reviewer-s6",
        json=resolve_body(submitted, started, **change))
    assert response.status_code in {404, 409}, response.text
    assert (business(claims, submitted), cases.events(started["case_id"], actor=OWNER)) == before


def test_http_expired_approval_and_permission_gate_fail_closed(http, monkeypatch):
    client, claims, cases, _ = http
    submitted = client.submit()
    started = client.action(client.action(submitted["handoff"], "claim"), "start")
    before = business(claims, submitted)
    monkeypatch.setenv("REACT_AGENT_APPROVAL_MODE", "deny")
    denied = client.request("POST", f"/cases/{started['case_id']}/resolve", actor="reviewer-s6",
        json=resolve_body(submitted, started))
    assert denied.status_code == 404, denied.text
    assert business(claims, submitted) == before
    monkeypatch.setenv("REACT_AGENT_APPROVAL_MODE", "auto_allow")
    with claims._engine.begin() as connection:
        connection.execute(update(claims._reviews).where(claims._reviews.c.approval_id == submitted["approval_id"])
            .values(approval_status="expired"))
    expired = client.request("POST", f"/cases/{started['case_id']}/resolve", actor="reviewer-s6",
        json=resolve_body(submitted, started))
    assert expired.status_code == 409, expired.text
    assert claims.get(submitted["claim_id"], actor_id=OWNER.actor_id)["status"] == "under_review"


def test_http_unbound_case_can_complete_work_only(http):
    client, claims, cases, routing = http
    # H1 permits cases predating a valid approval binding. Seed that path explicitly.
    claims._handoff_cases = None
    bound, submitted = seed(claims)
    claims.enable_handoff(routing)
    response = client.request("POST", "/cases", json={**bound, "approval_id": None})
    assert response.status_code == 200, response.text
    created = response.json()["case"]
    started = client.action(client.action(created, "claim"), "start")
    before = business(claims, submitted)
    response = client.request("POST", f"/cases/{started['case_id']}/resolve", actor="reviewer-s6",
        json=resolve_body({**submitted, "version": 1}, started, approval_id=None, decision="complete"))
    assert response.status_code == 200, response.text
    assert response.json()["case"]["status"] == "resolved"
    assert business(claims, submitted) == before


def test_http_identity_spoofing_and_unauthorized_access_are_hidden(http):
    client, _, _, _ = http
    submitted = client.submit()
    case = submitted["handoff"]
    spoof = {"X-Role": "finance_admin", "X-Queue-Ids": "finance_review", "X-Assignee-Id": "reviewer-s6"}
    for path in (f"/cases/{case['case_id']}", f"/cases/{case['case_id']}/events", "/cases/missing"):
        response = client.request("GET", path, actor="outsider", headers=spoof)
        assert response.status_code == 404 and response.json()["error"]["code"] == "case_not_found"
    for action in ("claim", "start", "release", "transfer", "escalate", "needs_applicant"):
        response = client.request("POST", f"/cases/{case['case_id']}/{action}", actor="outsider", headers=spoof,
            json={"expected_case_version": 1, "reason": "spoof"})
        assert response.status_code == 404 and response.json()["error"]["code"] == "case_not_found"
    for path, body in (("/cases", binding(submitted)),
            (f"/cases/{case['case_id']}/resolve", resolve_body(submitted, case))):
        response = client.request("POST", path, actor="outsider", headers=spoof, json=body)
        assert response.status_code == 404 and response.json()["error"]["code"] == "case_not_found"
    payload = client.request("POST", f"/cases/{case['case_id']}/claim", actor="reviewer-s6",
        json={"expected_case_version": 1, "assignee_id": "other", "role": "finance_admin"})
    assert payload.status_code == 422
    for headers, status in (({"Authorization": ""}, 401), ({"X-Actor-Id": ""}, 404)):
        assert client.request("GET", f"/cases/{case['case_id']}", headers=headers).status_code == status


def test_http_release_transfer_and_explicit_applicant_resume(http):
    client, claims, cases, _ = http
    submitted = client.submit()
    assigned = client.action(submitted["handoff"], "claim")
    released = client.action(assigned, "release", reason="shift ended")
    assert released["status"] == "queued" and released["assignee_id"] is None
    started = client.action(client.action(released, "claim"), "start")
    waiting = client.action(started, "needs_applicant", reason="receipt reference needed")
    before = business(claims, submitted)
    resumed = client.action(waiting, "resume", actor=OWNER.actor_id,
        claim_version=1, decision_hash=submitted["decision"]["decision_hash"],
        evidence_ref="receipt:supplement", reason="provided reference")
    assert resumed["status"] == "queued" and resumed["assignee_id"] is None
    assert resumed["response_due_at"] == waiting["response_due_at"]
    assert business(claims, submitted) == before
    transferred = client.action(resumed, "transfer", reason="senior review", target_queue_id="finance_admin")
    assert transferred["queue_id"] == "finance_admin"
    last = cases.events(transferred["case_id"], actor=OWNER)[-1]
    assert last["metadata"]["reason"] == "senior review"


def test_legacy_reason_is_blocked_without_changing_hash(http):
    # Existing real-Workflow HTTP lifecycle separately covers S5 compatibility.
    # Here exercise the persisted free-text reason in the same enabled SQL store.
    _, claims, cases, _ = http
    bound, submitted = seed(claims, reason="legacy free text")
    assert submitted["handoff"] == {"status": "blocked", "error_code": "invalid_handoff"}
    assert submitted["decision"]["decision_hash"] == bound["decision_hash"]
    assert cases.list_cases(actor=OWNER) == []


def test_auto_creation_failure_rolls_back_submission_and_review(http):
    client, claims, cases, _ = http
    def fail(connection, cursor, statement, parameters, context, many):
        if statement.startswith("INSERT INTO expense_case_outbox"):
            raise RuntimeError("synthetic intent write failure")
    event.listen(claims._engine, "before_cursor_execute", fail)
    try:
        response = client.request("POST", "/claims", json={"category": "meal", "amount": 128})
        claim_id = response.json()["claim_id"]
        failed = client.request("POST", f"/claims/{claim_id}/submit", json={"expected_version": 1})
        assert failed.status_code == 409, failed.text
    finally:
        event.remove(claims._engine, "before_cursor_execute", fail)
    assert claims.get(claim_id, actor_id=OWNER.actor_id)["status"] == "draft"
    assert claims.list_reviews(claim_id=claim_id) == []
    assert cases.list_cases(actor=OWNER) == []
    assert [e["event_type"] for e in claims.events(claim_id, actor_id=OWNER.actor_id)] == ["claim_created"]
    with claims._engine.connect() as connection:
        assert connection.execute(select(func.count()).select_from(cases._outbox)).scalar_one() == 0


@pytest.mark.parametrize("unavailable", [False, True])
def test_http_no_matching_route_is_persisted_unrouted(http, unavailable):
    client, claims, cases, routing = http
    config = replace(routing, queues=tuple(replace(q, available=False) for q in routing.queues)) if unavailable else replace(routing, rules=())
    claims.enable_handoff(config)
    submitted = client.submit()
    assert submitted["handoff"]["status"] == "unrouted"
    assert submitted["handoff"]["error_code"] == ("queue_unavailable" if unavailable else "unrouted_case")
    assert submitted["status"] == "under_review"


def test_real_workflow_legacy_reason_stays_blocked_on_http(http, monkeypatch):
    from react_agent.apps.expense import service
    client, claims, cases, _ = http
    monkeypatch.setattr(service, "_run_submit_workflow", client.real_workflow)
    created = client.request("POST", "/claims", json={"category": "meal", "amount": 128,
        "currency": "USD", "occurred_on": "2026-11-13", "description": "synthetic real rules",
        "business_purpose": "client meeting", "has_receipt": True, "receipt_refs": ["receipt-real-rule"],
        "expense_type": "business_meal", "participants": [OWNER.actor_id], "pre_approved": False})
    claim_id = created.json()["claim_id"]
    response = client.request("POST", f"/claims/{claim_id}/submit", json={"expected_version": 1})
    assert response.status_code == 200, response.text
    submitted = response.json()
    assert submitted["handoff"] == {"status": "blocked", "error_code": "invalid_handoff"}
    assert submitted["approval_id"]
    before = submitted["decision"]["decision_hash"]
    blocked = client.request("POST", "/cases", json={**binding(submitted), "reason_code": "approval_record_required"})
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "invalid_handoff"
    assert claims.list_reviews(claim_id=claim_id)[0]["decision"]["decision_hash"] == before
    assert cases.list_cases(actor=OWNER) == []


def test_http_replaced_claim_version_and_foreign_approval_fail(http):
    client, claims, cases, _ = http
    submitted = client.submit()
    other = client.submit()
    started = client.action(client.action(submitted["handoff"], "claim"), "start")
    before = business(claims, submitted)
    foreign = client.request("POST", f"/cases/{started['case_id']}/resolve", actor="reviewer-s6",
        json=resolve_body(submitted, started, approval_id=other["approval_id"]))
    assert foreign.status_code in {404, 409}
    assert business(claims, submitted) == before
    with claims._engine.begin() as connection:
        connection.execute(update(claims._claims).where(claims._claims.c.claim_id == submitted["claim_id"])
            .values(current_version=2))
    before = business(claims, submitted), cases.events(started["case_id"], actor=OWNER)
    replaced = client.request("POST", f"/cases/{started['case_id']}/resolve", actor="reviewer-s6",
        json=resolve_body(submitted, started))
    assert replaced.status_code == 409 and replaced.json()["error"]["code"] == "claim_version_mismatch"
    assert (business(claims, submitted), cases.events(started["case_id"], actor=OWNER)) == before


def test_server_configuration_errors_fail_closed(tmp_path, monkeypatch):
    from react_agent.server import fastapi_app

    monkeypatch.setenv("REACT_AGENT_DATABASE_URL", f"sqlite:///{tmp_path / 'config.sqlite'}")
    monkeypatch.setenv("REACT_AGENT_EXPENSE_CASE_ROUTING_FILE", str(tmp_path / "missing-routing.json"))
    monkeypatch.delenv("REACT_AGENT_EXPENSE_CASE_ACTORS_FILE", raising=False)
    monkeypatch.setenv("REACT_AGENT_AUTH_TOKEN", "synthetic-s6-token")
    client = HTTP(fastapi_app.create_app(initialize_runtime=False))
    bad_route = client.request("GET", "/cases")
    assert bad_route.status_code == 503 and bad_route.json()["error"]["code"] == "invalid_routing_config"
    # Existing S5 only falls back for ValueError/no database; configured route
    # failure is a structured storage error and cannot use that fallback.
    with pytest.raises(ExpenseStoreError) as exc:
        fastapi_app._expense_store()
    assert exc.value.code == "invalid_routing_config" and not isinstance(exc.value, ValueError)
    monkeypatch.delenv("REACT_AGENT_EXPENSE_CASE_ROUTING_FILE")
    malformed = tmp_path / "malformed-actors.json"
    malformed.write_text('{"actor": {"role": "invented_admin"}}', encoding="utf-8")
    monkeypatch.setenv("REACT_AGENT_EXPENSE_CASE_ACTORS_FILE", str(malformed))
    bad_actor = client.request("GET", "/cases")
    assert bad_actor.status_code == 503 and bad_actor.json()["error"]["code"] == "identity_unavailable"
    monkeypatch.delenv("REACT_AGENT_EXPENSE_CASE_ACTORS_FILE")
    assert client.request("GET", "/queues").json()["queues"] == []
