"""Opt-in browser smoke for S7 ops views: timeline, queues, concurrent claim, bound resolve.

Install .[browser], set REACT_AGENT_BROWSER_SMOKE=1, then run this file.
Uses controlled Decision handoff (same wiring as S6 HTTP) so submit creates a
case; Claim/case APIs and permission gate stay real. No mocked case endpoints.
"""
from __future__ import annotations

import json
import os
import re
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("REACT_AGENT_BROWSER_SMOKE") != "1", reason="opt-in browser smoke")

TOKEN = "synthetic-s7-ops-token"
APPLICANT = "employee-s7-ops"
REVIEWER_A = "reviewer-s7-a"
REVIEWER_B = "reviewer-s7-b"
ADMIN = "admin-s7-ops"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "X-Actor-Id": APPLICANT}


@pytest.fixture
def ops(tmp_path, monkeypatch, request):
    playwright = pytest.importorskip("playwright.sync_api")
    uvicorn = pytest.importorskip("uvicorn")
    from react_agent.apps.expense import service
    from react_agent.apps.expense.domain import Decision, Handoff
    from react_agent.server import fastapi_app

    monkeypatch.setenv("REACT_AGENT_DATABASE_URL", f"sqlite:///{tmp_path / 'ops.sqlite'}")
    monkeypatch.setenv("REACT_AGENT_AUTH_TOKEN", TOKEN)
    monkeypatch.setenv("REACT_AGENT_APPROVAL_MODE", "auto_allow")
    monkeypatch.setenv("REACT_AGENT_PERMISSION_GATE", "1")
    monkeypatch.setenv("REACT_AGENT_APPROVAL_DIR", str(tmp_path / "approvals"))
    monkeypatch.setenv("REACT_AGENT_HOST_VALIDATION", "loopback")
    directory = tmp_path / "actors.json"
    directory.write_text(json.dumps({
        REVIEWER_A: {"role": "finance_reviewer", "queue_ids": ["finance_review"]},
        REVIEWER_B: {"role": "finance_reviewer", "queue_ids": ["finance_review"]},
        ADMIN: {"role": "finance_admin", "queue_ids": ["finance_review", "finance_admin"]},
    }), encoding="utf-8")
    monkeypatch.setenv("REACT_AGENT_EXPENSE_CASE_ACTORS_FILE", str(directory))
    for name in ("REACT_AGENT_API_KEY", "REACT_AGENT_EXPENSE_CASE_ROUTING_FILE", "REACT_AGENT_REQUIRE_HOST_ALLOWLIST", "REACT_AGENT_ALLOWED_HOSTS", "REACT_AGENT_STRICT_CONFIRM", "REACT_AGENT_SANDBOX_REQUIRED"):
        monkeypatch.delenv(name, raising=False)

    def controlled(claim, **kwargs):
        decision = Decision(
            decision="needs_review",
            reasons=("synthetic controlled receipt check",),
            decision_source="rules",
            decision_model="s7-ops-smoke-v1",
            rule_result="matched",
            review_required=True,
            handoff=Handoff("receipt_manual_verification", "medium", "100-500"),
            claim_id=claim["claim_id"],
            claim_version=claim["version"],
            policy_version="expense-policy-sim-v1",
        )
        return {"ok": True, "state": {"decision": decision.to_dict()}, "run_id": "s7-ops-synthetic"}

    monkeypatch.setattr(service, "_run_submit_workflow", controlled)
    app = fastapi_app.create_app(initialize_runtime=False)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    base = f"http://127.0.0.1:{sock.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    output = Path("artifacts/expense/smoke/s7-ops") / re.sub(r"[^a-zA-Z0-9_.-]", "_", request.node.name)
    output.mkdir(parents=True, exist_ok=True)
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            assert thread.is_alive() and time.monotonic() < deadline, "HTTP server did not start"
            time.sleep(0.02)
        import httpx
        warmed = httpx.get(f"{base}/v1/expense/queues", headers=api_headers(REVIEWER_A), timeout=20)
        assert warmed.status_code == 200, warmed.text
        store = next(iter(fastapi_app._EXPENSE_STORES.values()))
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(channel=os.environ.get("REACT_AGENT_BROWSER_CHANNEL", "chrome"), headless=True)
            context = browser.new_context(viewport={"width": 1280, "height": 1000})
            page = context.new_page()
            page.set_default_timeout(15000)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            try:
                yield {
                    "page": page,
                    "context": context,
                    "browser": browser,
                    "api": context.request,
                    "base": base,
                    "output": output,
                    "playwright": playwright,
                    "store": store,
                }
                assert not errors, errors
            finally:
                page.screenshot(path=str(output / "final.png"), full_page=True)
                context.close()
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        for key in list(fastapi_app._EXPENSE_STORES):
            store = fastapi_app._EXPENSE_STORES.pop(key, None)
            if store:
                store.close()


def fill_applicant(page):
    for key, value in {
        "amount": "128",
        "occurred_on": "2026-11-14",
        "description": "客户会议餐费",
        "business_purpose": "项目讨论",
        "receipt_refs": "synthetic-receipt-s7-ops",
        "participants": APPLICANT,
    }.items():
        page.locator("#" + key).fill(value)


def submit_claim(page, base, token=TOKEN, actor=APPLICANT):
    from playwright.sync_api import expect

    page.goto(base + "/expense")
    page.locator("#token").fill(token)
    page.locator("#actor").fill(actor)
    fill_applicant(page)
    page.get_by_role("button", name="保存草稿", exact=True).click()
    expect(page.locator("#claim-status")).to_have_text("草稿")
    page.locator("#submit").click()
    expect(page.locator("#claim-status")).to_have_text("待审")
    return page.locator("#lookup").input_value()


def open_ops(page, base, actor, token=TOKEN):
    page.goto(base + "/expense/ops")
    page.locator("#token").fill(token)
    page.locator("#actor").fill(actor)


def api_headers(actor):
    return {"Authorization": f"Bearer {TOKEN}", "X-Actor-Id": actor}


def test_timeline_queue_list_and_bound_resolve(ops):
    from playwright.sync_api import expect

    page, api, base, output = ops["page"], ops["api"], ops["base"], ops["output"]
    claim_id = submit_claim(page, base)
    expect(page.locator("#case-status")).to_have_text("工单排队中")
    expect(page.locator("#case-events")).to_contain_text("创建工单")
    expect(page.locator("#case-meta")).to_contain_text("finance_review")
    page.screenshot(path=str(output / "applicant-timeline.png"), full_page=True)

    claim = api.get(f"{base}/v1/expense/claims/{claim_id}", headers=HEADERS).json()
    assert claim["status"] == "under_review"
    cases = api.get(f"{base}/v1/expense/cases", headers=api_headers(REVIEWER_A)).json()["cases"]
    assert len(cases) == 1 and cases[0]["claim_id"] == claim_id
    case_id = cases[0]["case_id"]

    open_ops(page, base, REVIEWER_A)
    page.locator("#refresh-all").click()
    expect(page.locator("#queues")).to_contain_text("财务审核")
    expect(page.locator("#cases")).to_contain_text(case_id)
    page.get_by_role("button", name="打开", exact=True).click()
    expect(page.locator("#case-status")).to_have_text("排队待审")
    expect(page.locator("#binding")).to_contain_text(claim["approval_id"])
    page.locator("#claim").click()
    expect(page.locator("#case-status")).to_have_text("已认领")
    page.locator("#start").click()
    expect(page.locator("#case-status")).to_have_text("处理中")
    page.locator("#decision").select_option("approve")
    page.locator("#resolve-reason").fill("凭证已人工核对")
    page.locator("#resolve").click()
    expect(page.locator("#case-status")).to_have_text("工单已关闭")
    expect(page.locator("#feedback")).to_contain_text("批准处理结果")
    assert "已付款" not in page.locator("main").inner_text()
    page.screenshot(path=str(output / "ops-resolved.png"), full_page=True)

    refreshed = api.get(f"{base}/v1/expense/claims/{claim_id}", headers=HEADERS).json()
    assert refreshed["status"] == "approved"
    assert refreshed["review"]["resolution"]["approver_id"] == REVIEWER_A

    page.goto(base + "/expense")
    page.locator("#token").fill(TOKEN)
    page.locator("#actor").fill(APPLICANT)
    page.locator("#lookup").fill(claim_id)
    page.locator("#load").click()
    expect(page.locator("#claim-status")).to_have_text("已批准")
    expect(page.locator("#case-status")).to_have_text("工单已关闭")
    expect(page.locator("#case-events")).to_contain_text("关闭工单")
    expect(page.locator("#case-meta")).to_contain_text("不等于批准报销")


def test_concurrent_claim_release_transfer_escalate(ops):
    from playwright.sync_api import expect
    import httpx

    page, api, base, browser, output = ops["page"], ops["api"], ops["base"], ops["browser"], ops["output"]
    claim_id = submit_claim(page, base)
    case = api.get(f"{base}/v1/expense/cases", headers=api_headers(REVIEWER_A)).json()["cases"][0]
    case_id = case["case_id"]
    version = case["case_version"]

    barrier = Barrier(2)

    def claim(actor):
        barrier.wait(timeout=10)
        return httpx.post(
            f"{base}/v1/expense/cases/{case_id}/claim",
            headers={**api_headers(actor), "Idempotency-Key": f"claim-{actor}-{case_id}"},
            json={"expected_case_version": version},
            timeout=20,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(claim, (REVIEWER_A, REVIEWER_B)))
    assert sorted(r.status_code for r in responses) == [200, 409]
    loser = next(r for r in responses if r.status_code != 200)
    assert loser.json()["error"]["code"] == "case_already_claimed"
    winner = next(r.json()["case"] for r in responses if r.status_code == 200)
    winner_id = winner["assignee_id"]

    # Loser verifies the same conflict through the ops page after a refresh.
    loser_id = REVIEWER_B if winner_id == REVIEWER_A else REVIEWER_A
    loser_context = browser.new_context(viewport={"width": 1280, "height": 1000})
    loser_page = loser_context.new_page()
    try:
        open_ops(loser_page, base, loser_id)
        loser_page.locator("#refresh-all").click()
        expect(loser_page.locator("#cases")).to_contain_text(case_id)
        loser_page.get_by_role("button", name="打开", exact=True).click()
        expect(loser_page.locator("#case-status")).to_have_text("已认领")
        loser_page.locator("#claim").click()
        expect(loser_page.locator("#feedback")).to_contain_text("case_already_claimed")
        loser_page.screenshot(path=str(output / "concurrent-loser.png"), full_page=True)
    finally:
        loser_context.close()

    open_ops(page, base, winner_id)
    page.locator("#refresh-all").click()
    page.get_by_role("button", name="打开", exact=True).click()
    expect(page.locator("#assignee")).to_contain_text(winner_id)
    page.locator("#reason").fill("shift ended")
    page.locator("#release").click()
    expect(page.locator("#case-status")).to_have_text("排队待审")
    page.locator("#claim").click()
    expect(page.locator("#case-status")).to_have_text("已认领")
    page.locator("#target-queue").fill("finance_admin")
    page.locator("#reason").fill("needs senior review")
    with page.expect_response(lambda response: "/transfer" in response.url) as transfer_wait:
        page.locator("#transfer").click()
    transfer = transfer_wait.value
    assert transfer.ok, transfer.text()
    expect(page.locator("#feedback")).to_contain_text("已转派")
    expect(page.locator("#case-status")).to_have_text("排队待审")
    # Reviewer loses finance_admin visibility; timeline is hidden as case_not_found.
    expect(page.locator("#case-events")).to_contain_text("case_not_found")
    open_ops(page, base, ADMIN)
    page.locator("#refresh-all").click()
    expect(page.locator("#queues")).to_contain_text("财务升级审核")
    page.get_by_role("button", name="打开", exact=True).click()
    page.locator("#claim").click()
    expect(page.locator("#case-status")).to_have_text("已认领")
    page.locator("#reason").fill("policy conflict")
    with page.expect_response(lambda response: "/escalate" in response.url) as escalate_wait:
        page.locator("#escalate").click()
    assert escalate_wait.value.ok, escalate_wait.value.text()
    expect(page.locator("#case-status")).to_have_text("已升级")
    expect(page.locator("#case-events")).to_contain_text("升级队列")
    assert api.get(f"{base}/v1/expense/claims/{claim_id}", headers=HEADERS).json()["status"] == "under_review"


def test_complete_without_approval_and_bound_reject(ops):
    from playwright.sync_api import expect

    page, api, base = ops["page"], ops["api"], ops["base"]

    # Unbound case (explicit approval_id null): desk may end human work only.
    store = ops["store"]
    cases = store._handoff_cases
    store._handoff_cases = None
    created = api.post(
        f"{base}/v1/expense/claims",
        headers={**HEADERS, "Idempotency-Key": "unbound-create"},
        data={
            "category": "meal", "amount": 128, "currency": "USD", "occurred_on": "2026-11-14",
            "description": "unbound work case", "business_purpose": "ops smoke",
            "has_receipt": True, "receipt_refs": ["receipt-unbound"], "expense_type": "business_meal",
            "participants": [APPLICANT],
        },
    )
    assert created.ok, created.text()
    unbound_claim = created.json()["claim_id"]
    submitted = api.post(
        f"{base}/v1/expense/claims/{unbound_claim}/submit",
        headers={**HEADERS, "Idempotency-Key": "unbound-submit"},
        data={"expected_version": 1},
    )
    assert submitted.ok, submitted.text()
    store._handoff_cases = cases
    body = submitted.json()
    unbound = api.post(
        f"{base}/v1/expense/cases",
        headers={**HEADERS, "Idempotency-Key": "unbound-case"},
        data={
            "claim_id": unbound_claim,
            "claim_version": body["version"],
            "decision_hash": body["decision"]["decision_hash"],
            "approval_id": None,
        },
    )
    assert unbound.ok, unbound.text()
    assert unbound.json()["case"]["approval_id"] is None

    open_ops(page, base, REVIEWER_A)
    page.locator("#refresh-all").click()
    page.get_by_role("button", name="打开", exact=True).first.click()
    page.locator("#claim").click()
    page.locator("#start").click()
    expect(page.locator("#case-status")).to_have_text("处理中")
    page.locator("#decision").select_option("complete")
    expect(page.locator("#approval-id")).to_have_value("")
    page.locator("#claim-version").fill(str(body["version"]))
    page.locator("#decision-hash").fill(body["decision"]["decision_hash"])
    page.locator("#resolve-reason").fill("close human work only")
    page.locator("#resolve").click()
    expect(page.locator("#case-status")).to_have_text("工单已关闭")
    expect(page.locator("#feedback")).to_contain_text("人工作业已结束")
    assert api.get(f"{base}/v1/expense/claims/{unbound_claim}", headers=HEADERS).json()["status"] == "under_review"

    # Bound case: approve/reject require legal approval; complete with null fails closed.
    claim_id = submit_claim(page, base)
    claim = api.get(f"{base}/v1/expense/claims/{claim_id}", headers=HEADERS).json()
    case = api.get(f"{base}/v1/expense/cases", headers=api_headers(REVIEWER_A)).json()["cases"]
    active = next(c for c in case if c["claim_id"] == claim_id and c["status"] != "resolved")
    assigned = api.post(
        f"{base}/v1/expense/cases/{active['case_id']}/claim",
        headers={**api_headers(REVIEWER_A), "Idempotency-Key": "claim-bound-path"},
        data={"expected_case_version": active["case_version"]},
    ).json()["case"]
    started = api.post(
        f"{base}/v1/expense/cases/{assigned['case_id']}/start",
        headers={**api_headers(REVIEWER_A), "Idempotency-Key": "start-bound-path"},
        data={"expected_case_version": assigned["case_version"]},
    ).json()["case"]

    open_ops(page, base, REVIEWER_A)
    page.locator("#refresh-all").click()
    page.locator("#cases").get_by_text(started["case_id"]).locator("xpath=ancestor::tr").get_by_role("button", name="打开").click()
    expect(page.locator("#case-status")).to_have_text("处理中")
    page.locator("#decision").select_option("complete")
    page.locator("#resolve-reason").fill("cannot complete over bound approval")
    page.locator("#resolve").click()
    expect(page.locator("#feedback")).to_contain_text("approval_binding_mismatch")
    assert api.get(f"{base}/v1/expense/claims/{claim_id}", headers=HEADERS).json()["status"] == "under_review"

    page.locator("#decision").select_option("reject")
    page.locator("#approval-id").fill(claim["approval_id"])
    page.locator("#claim-version").fill(str(claim["version"]))
    page.locator("#decision-hash").fill(claim["decision"]["decision_hash"])
    page.locator("#resolve-reason").fill("receipt insufficient")
    page.locator("#resolve").click()
    expect(page.locator("#case-status")).to_have_text("工单已关闭")
    expect(page.locator("#feedback")).to_contain_text("拒绝处理结果")
    assert api.get(f"{base}/v1/expense/claims/{claim_id}", headers=HEADERS).json()["status"] == "rejected"


def test_unauthorized_actor_sees_empty_queues(ops):
    from playwright.sync_api import expect

    page, api, base = ops["page"], ops["api"], ops["base"]
    submit_claim(page, base)
    case_id = api.get(f"{base}/v1/expense/cases", headers=api_headers(REVIEWER_A)).json()["cases"][0]["case_id"]

    open_ops(page, base, "outsider-s7")
    page.locator("#refresh-all").click()
    expect(page.locator("#queues")).to_contain_text("无可见队列")
    expect(page.locator("#cases")).to_contain_text("暂无待审工单")
    hidden = api.get(f"{base}/v1/expense/cases/{case_id}", headers=api_headers("outsider-s7"))
    assert hidden.status == 404 and hidden.json()["error"]["code"] == "case_not_found"
