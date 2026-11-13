"""Opt-in browser smoke against real HTTP/SQL/Workflow; no mocked Claim API.

Install .[browser], then set REACT_AGENT_BROWSER_SMOKE=1 and run this file.
Chrome is reused by default (REACT_AGENT_BROWSER_CHANNEL can select msedge).
Only transport failures are injected; approval is performed through existing
S5 HTTP by a separate synthetic reviewer, never by the applicant page.
"""
from __future__ import annotations

import os
import re
import socket
import threading
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("REACT_AGENT_BROWSER_SMOKE") != "1", reason="opt-in browser smoke")

TOKEN = "synthetic-s7-form-token"
ACTOR = "employee-s7"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "X-Actor-Id": ACTOR}


@pytest.fixture
def ui(tmp_path, monkeypatch, request):
    playwright = pytest.importorskip("playwright.sync_api")
    uvicorn = pytest.importorskip("uvicorn")
    from react_agent.server import fastapi_app

    monkeypatch.setenv("REACT_AGENT_DATABASE_URL", f"sqlite:///{tmp_path / 'claims.sqlite'}")
    monkeypatch.setenv("REACT_AGENT_AUTH_TOKEN", TOKEN)
    monkeypatch.setenv("REACT_AGENT_APPROVAL_MODE", "auto_allow")
    for name in ("REACT_AGENT_API_KEY", "REACT_AGENT_EXPENSE_CASE_ACTORS_FILE", "REACT_AGENT_EXPENSE_CASE_ROUTING_FILE", "REACT_AGENT_REQUIRE_HOST_ALLOWLIST", "REACT_AGENT_ALLOWED_HOSTS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("REACT_AGENT_HOST_VALIDATION", "loopback")
    app = fastapi_app.create_app(initialize_runtime=False)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    base = f"http://127.0.0.1:{sock.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    output = Path("artifacts/expense/smoke/s7-form") / re.sub(r"[^a-zA-Z0-9_.-]", "_", request.node.name)
    output.mkdir(parents=True, exist_ok=True)
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            assert thread.is_alive() and time.monotonic() < deadline, "HTTP server did not start"
            time.sleep(.02)
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(channel=os.environ.get("REACT_AGENT_BROWSER_CHANNEL", "chrome"), headless=True)
            context = browser.new_context(viewport={"width": 1280, "height": 1000})
            page = context.new_page()
            page.set_default_timeout(10000)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            try:
                page.goto(base + "/expense")  # No pre-injected authentication.
                page.locator("#token").fill(TOKEN)
                page.locator("#actor").fill(ACTOR)
                yield page, context.request, base, output
                assert not errors, errors
            finally:
                page.screenshot(path=str(output / "final.png"), full_page=True)
                context.close()
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        store = fastapi_app._EXPENSE_STORES.pop(os.environ["REACT_AGENT_DATABASE_URL"], None)
        if store:
            store.close()


def fill(page):
    for key, value in {"amount":"128", "occurred_on":"2026-11-12", "description":"客户会议餐费", "business_purpose":"项目讨论", "receipt_refs":"synthetic-receipt-s7", "participants":ACTOR}.items():
        page.locator("#" + key).fill(value)


def wait_status(page, text):
    from playwright.sync_api import expect
    expect(page.locator("#claim-status")).to_have_text(text)
    expect(page.locator("#refresh")).to_be_enabled()


def saved(page):
    fill(page)
    page.get_by_role("button", name="保存草稿", exact=True).click()
    wait_status(page, "草稿")
    return page.locator("#lookup").input_value()


def read(api, base, claim_id, suffix=""):
    result = api.get(f"{base}/v1/expense/claims/{claim_id}{suffix}", headers=HEADERS)
    assert result.ok, result.text()
    return result.json()


@pytest.mark.parametrize("decision,label", [("approve", "已批准"), ("reject", "已拒绝")], ids=["approved", "rejected"])
def test_form_lifecycle_and_review_result(ui, decision, label):
    from playwright.sync_api import expect
    page, api, base, output = ui
    claim_id = saved(page)
    page.locator("#amount").fill("140")
    expect(page.locator("#submit")).to_be_disabled()
    page.get_by_role("button", name="保存草稿", exact=True).click()
    expect(page.locator("#claim-meta")).to_contain_text("版本 2")
    expect(page.locator("#submit")).to_be_enabled()
    page.locator("#submit").click()
    wait_status(page, "待审")
    expect(page.locator("#amount")).to_be_disabled()
    expect(page.locator("#save")).to_be_disabled()
    data = read(api, base, claim_id)
    response = api.post(f"{base}/v1/expense/reviews/{data['approval_id']}/resolve", headers={**HEADERS, "Idempotency-Key":"synthetic-s7-review"}, data={
        "claim_id":claim_id, "expected_version":2, "decision_hash":data["decision"]["decision_hash"],
        "decision":decision, "approver_id":"synthetic-manager-s7", "comment":"凭证已复核 <script>unsafe()</script>",
    })
    assert response.ok, response.text()
    page.locator("#refresh").click()
    wait_status(page, label)
    expect(page.locator("#resolution")).to_contain_text("synthetic-manager-s7")
    expect(page.locator("#resolution")).to_contain_text("<script>unsafe()</script>")
    expect(page.locator("#events")).to_contain_text("记录审批结果")
    expect(page.locator("#amount")).to_be_disabled()
    page.screenshot(path=str(output / "desktop.png"), full_page=True)
    # Recovery in a new page uses only the known Claim ID, not browser storage.
    page.reload()
    assert page.locator("#token").input_value() == ""
    page.locator("#token").fill(TOKEN)
    page.locator("#actor").fill(ACTOR)
    page.locator("#lookup").fill(claim_id)
    page.locator("#load").click()
    wait_status(page, label)
    page.set_viewport_size({"width":375,"height":812})
    page.screenshot(path=str(output / "narrow.png"), full_page=True)
    boxes = page.locator("input:visible,select:visible,textarea:visible").evaluate_all("els=>els.map(e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom};})")
    assert all(b["x"] >= 0 and b["right"] <= 375 for b in boxes)
    for i, a in enumerate(boxes):
        for b in boxes[i+1:]:
            assert a["right"] <= b["x"] or b["right"] <= a["x"] or a["bottom"] <= b["y"] or b["bottom"] <= a["y"]
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


@pytest.mark.parametrize("operation", ["create", "update", "submit"])
def test_response_loss_reuses_idempotency_key(ui, operation):
    from playwright.sync_api import expect
    page, api, base, _ = ui
    claim_id = None if operation == "create" else saved(page)
    if operation == "create":
        fill(page)
    if operation == "update":
        page.locator("#amount").fill("140")
    path = "**/v1/expense/claims" if operation == "create" else f"**/v1/expense/claims/{claim_id}" + ("/submit" if operation == "submit" else "")
    requests, first = [], []
    def lose_response(route):
        requests.append((route.request.headers.get("idempotency-key"), route.request.post_data))
        if not first:
            response = route.fetch()  # The real server commits; browser loses response.
            assert response.ok, response.text()
            first.append(response.json())
            route.abort("failed")
        else:
            route.continue_()
    page.route(path, lose_response)
    button = "#submit" if operation == "submit" else "#save"
    # Two same-turn clicks exercise the UI's in-flight guard.
    page.locator(button).evaluate("b=>{b.click();b.click();}")
    expect(page.locator("#retry")).to_be_visible()
    expect(page.locator("#amount")).to_be_disabled()
    assert len(requests) == 1
    page.locator("#retry").click()
    wait_status(page, "待审" if operation == "submit" else "草稿")
    assert len(requests) == 2 and requests[0] == requests[1] and requests[0][0]
    events = read(api, base, first[0]["claim_id"], "/events")["events"]
    event_type = {"create":"claim_created", "update":"claim_updated", "submit":"claim_submitted"}[operation]
    assert sum(e["event_type"] == event_type for e in events) == 1
    if operation == "submit":
        assert sum(e["event_type"] == "review_routed" for e in events) == 1


def test_stale_version_not_found_and_read_failure(ui):
    from playwright.sync_api import expect
    page, api, base, _ = ui
    claim_id = saved(page)
    response = api.patch(f"{base}/v1/expense/claims/{claim_id}", headers={**HEADERS,"Idempotency-Key":"other-editor"}, data={"expected_version":1,"amount":150})
    assert response.ok
    page.locator("#amount").fill("160")
    page.locator("#save").click()
    expect(page.locator("#feedback")).to_contain_text("claim_version_mismatch")
    expect(page.locator("#save")).to_be_disabled()
    assert read(api, base, claim_id)["claim"]["amount"] == 150
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#refresh").click()
    expect(page.locator("#amount")).to_have_value("150")
    expect(page.locator("#save")).to_be_enabled()
    page.route(f"**/v1/expense/claims/{claim_id}", lambda route: route.abort())
    page.locator("#refresh").click()
    expect(page.locator("#feedback")).to_contain_text("网络异常")
    expect(page.locator("#save")).to_be_disabled()
    page.unroute(f"**/v1/expense/claims/{claim_id}")
    page.locator("#refresh").click()
    expect(page.locator("#save")).to_be_enabled()
    page.locator("#actor").fill("unrelated-employee")
    expect(page.locator("#claim-status")).to_have_text("未创建")
    expect(page.locator("#amount")).to_have_value("")
    page.locator("#lookup").fill(claim_id)
    page.locator("#load").click()
    expect(page.locator("#feedback")).to_have_text("not_found：未找到可访问的单据。")
    page.locator("#lookup").fill("missing-claim")
    page.locator("#load").click()
    expect(page.locator("#feedback")).to_have_text("not_found：未找到可访问的单据。")


def test_audit_read_failure_does_not_repeat_saved_write(ui):
    from playwright.sync_api import expect
    page, api, base, _ = ui
    page.route("**/events", lambda route: route.abort())
    fill(page)
    page.locator("#save").click()
    expect(page.locator("#feedback")).to_contain_text("单据操作已成功")
    expect(page.locator("#retry")).to_be_hidden()
    page.unroute("**/events")
    page.locator("#refresh").click()
    expect(page.locator("#events")).to_contain_text("创建草稿")
    assert len(read(api, base, page.locator("#lookup").input_value(), "/events")["events"]) == 1


@pytest.mark.parametrize("category,fields", [
    ("transport", {"transport_mode":"taxi", "route_scope":"intra_city", "seat_class":"standard"}),
    ("lodging", {"city_code":"CN-SH", "city_tier":"market_high", "check_in":"2026-11-12", "check_out":"2026-11-13", "nights":"1"}),
    ("office_purchase", {"purchase_order_id":"PO-123", "item_type":"keyboard"}),
])
def test_category_fields_and_client_validation(ui, category, fields):
    from playwright.sync_api import expect
    page, api, base, _ = ui
    page.locator("#save").click()
    expect(page.locator("#claim-status")).to_have_text("未创建")
    assert not page.locator("#amount").evaluate("e=>e.validity.valid")
    fill(page)
    page.locator("#category").select_option(category)
    for key, value in fields.items():
        locator = page.locator("#" + key)
        if locator.evaluate("e=>e.tagName") == "SELECT":
            locator.select_option(value)
        else:
            locator.fill(value)
    page.locator("#save").click()
    wait_status(page, "草稿")
    data = read(api, base, page.locator("#lookup").input_value())
    assert data["claim"]["category"] == category
    assert "expense_type" not in data["claim"]
    page.set_viewport_size({"width":320,"height":700})
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
