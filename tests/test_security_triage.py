"""Security Triage Agent MVP contract tests (network-free)."""
from __future__ import annotations

import asyncio
import json
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer

import pytest


@pytest.fixture(autouse=True)
def _offline_snapshot(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("REACT_AGENT_SECURITY_LIVE", raising=False)


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _triage(body: dict):
    from react_agent.apps.security_triage import run_triage

    return run_triage(body)


def test_known_cve_kev_and_inferred_attack_mapping():
    case = _triage({"cve_ids": ["CVE-2021-44228"]})["case"]
    assert case["mode"] == "offline_snapshot"
    assert case["cves"][0]["found"] is True
    assert case["cves"][0]["cvss_score"] == 10.0
    assert case["kev"][0]["listed"] is True
    assert case["attack_mappings"][0]["technique_id"] == "T1190"
    assert case["attack_mappings"][0]["mapping_type"] == "inferred"
    assert case["attack_mappings"][0]["authoritative"] is False


def test_known_cve_can_be_absent_from_bounded_kev_snapshot():
    case = _triage({"cve_ids": ["CVE-2020-11022"]})["case"]
    assert case["cves"][0]["found"] is True
    assert case["kev"][0]["listed"] is False
    assert case["kev"][0]["lookup_status"] == "not_listed_in_snapshot"


def test_unknown_cve_does_not_claim_nonexistence():
    case = _triage({"cve_ids": ["CVE-2099-9999"]})["case"]
    assert case["cves"][0]["found"] is False
    assert case["cves"][0]["lookup_status"] == "not_in_snapshot"
    assert "not a clean or safe verdict" in " ".join(case["limitations"])


def test_ioc_enrichment_and_no_hit_boundary():
    case = _triage({"iocs": ["example.invalid", "203.0.113.10"]})["case"]
    known, unknown = case["iocs"]
    assert known["verdict"] == "reserved"
    assert known["citation_id"] == "RFC2606"
    assert unknown["found"] is False
    assert unknown["malicious"] is None
    assert unknown["verdict"] == "not_observed_in_snapshot"


def test_message_extracts_cve_ip_domain_and_deduplicates():
    case = _triage(
        {
            "message": "研判 cve-2021-44228、8.8.8.8 和 example.invalid",
            "cve_ids": ["CVE-2021-44228"],
        }
    )["case"]
    assert [item["cve_id"] for item in case["cves"]] == ["CVE-2021-44228"]
    assert {item["ioc"] for item in case["iocs"]} == {"8.8.8.8", "example.invalid"}


def test_report_references_every_structured_citation():
    result = _triage({"cve_ids": ["CVE-2021-44228"], "iocs": ["example.invalid"]})
    case = result["case"]
    citation_ids = {citation["id"] for citation in case["citations"]}
    for item in [*case["cves"], *case["kev"], *case["attack_mappings"], *case["iocs"]]:
        assert item["citation_id"] in citation_ids
        assert f"[{item['citation_id']}]" in result["answer"]


def test_security_triage_emits_evaluation_episode_contract():
    result = _triage({"cve_ids": ["CVE-2021-44228"]})
    episode = result["episode"]
    assert episode["schema_version"] == "evaluation-episode/v1"
    assert episode["framework"] == "react-agent-security-triage"
    assert episode["expected_state"] == {}
    assert episode["final_state"]["security"]["review_status"] == "pending_review"
    assert episode["final_state"]["security"]["executed_actions"] == 0
    assert episode["trajectory"]["steps"]


def test_security_episode_routes_failed_state_to_feedback_target():
    from react_agent.apps.security_triage.episode import build_evaluation_episode

    result = _triage({"cve_ids": ["CVE-2021-44228"]})
    episode = build_evaluation_episode(
        {"cve_ids": ["CVE-2021-44228"]},
        result,
        episode_id="feedback-case",
        split="golden",
        expected={"priority": "critical"},
    )
    assert episode["state_verification"]["passed"] is False
    assert episode["metadata"]["failure_feedback"] == [
        {
            "signal": "priority",
            "target": "prompt",
            "action": "Review risk-priority instructions and recommendation selection.",
        }
    ]


def test_human_review_is_required_and_explicit():
    pending = _triage({"cve_ids": ["CVE-2021-44228"]})["case"]
    approved = _triage(
        {
            "cve_ids": ["CVE-2021-44228"],
            "review": {"decision": "approve", "reviewer": "analyst-01", "notes": "资产已核对"},
        }
    )["case"]
    rejected = _triage(
        {
            "cve_ids": ["CVE-2021-44228"],
            "review": {"decision": "reject", "reviewer": "analyst-02"},
        }
    )["case"]
    assert pending["status"] == "pending_review"
    assert approved["status"] == "approved"
    assert approved["review"]["reviewer"] == "analyst-01"
    assert rejected["status"] == "rejected"


def test_invalid_review_decision_is_rejected():
    from react_agent.apps.security_triage.offline_answer import answer_offline

    output = answer_offline(
        {"cve_ids": ["CVE-2021-44228"], "review": {"decision": "skip", "reviewer": "a"}}
    )
    assert output["ok"] is False
    assert output["error_code"] == "invalid_security_triage_request"


def test_every_action_is_advisory_and_no_action_is_executed():
    case = _triage({"cve_ids": ["CVE-2021-44228"], "iocs": ["example.invalid"]})["case"]
    assert case["read_only"] is True
    assert case["executed_actions"] == []
    assert all(item["execution"] == "not_executed" for item in case["recommendations"])
    assert all(item["requires_human_approval"] for item in case["recommendations"])


def test_request_supplied_sbom_correlates_assets_without_version_guessing():
    case = _triage(
        {
            "cve_ids": ["CVE-2021-44228", "CVE-2020-11022"],
            "assets": [
                {
                    "asset_id": "customer-api-01",
                    "name": "Customer API",
                    "criticality": "critical",
                    "internet_exposed": True,
                    "owner": "payments-platform",
                    "components": [
                        {
                            "component_id": "pkg-1",
                            "name": "log4j-core",
                            "version": "2.14.1",
                            "cve_ids": ["CVE-2021-44228"],
                            "source": "cyclonedx-import",
                        }
                    ],
                }
            ],
        }
    )["case"]
    log4j, jquery = case["asset_matches"]
    assert log4j["matched"] is True
    assert log4j["asset_count"] == 1
    assert log4j["matches"][0]["evidence_type"] == "declared_sbom_cve"
    assert jquery["matched"] is False
    assert case["recommendations"][0]["priority"] == "critical"
    assert any(item.get("source_type") == "organization_supplied" for item in case["citations"])


def test_cyclonedx_inline_sbom_is_read_only_and_correlated():
    case = _triage(
        {
            "cve_ids": ["CVE-2021-44228"],
            "sbom": {
                "asset_id": "sbom-edge-01",
                "criticality": "high",
                "internet_exposed": True,
                "document": {
                    "bomFormat": "CycloneDX",
                    "specVersion": "1.5",
                    "components": [
                        {
                            "bom-ref": "pkg:generic/log4j-core@2.14.1",
                            "name": "log4j-core",
                            "version": "2.14.1",
                            "vulnerabilities": [{"id": "CVE-2021-44228"}],
                        }
                    ],
                },
            },
        }
    )["case"]
    assert case["assets"][0]["sbom"]["format"] == "CycloneDX"
    assert case["asset_matches"][0]["matched"] is True
    assert case["assets"][0]["components"][0]["source"] == "cyclonedx_inline"


def test_llm_report_is_citation_bound_and_falls_back(monkeypatch: pytest.MonkeyPatch):
    from react_agent.apps.security_triage.llm_report import generate_llm_report

    case = _triage({"cve_ids": ["CVE-2021-44228"]})["case"]
    monkeypatch.setenv("REACT_AGENT_SECURITY_LLM", "1")
    invalid, metadata = generate_llm_report(
        case,
        chat=lambda prompt, evidence: {"content": "Invented fact [FAKE]"},
    )
    assert invalid is None
    assert metadata["fallback"] is True
    assert "unknown_citation_ids" in metadata["failure"]

    valid, valid_metadata = generate_llm_report(
        case,
        chat=lambda prompt, evidence: {
            "content": "Findings: CVE-2021-44228 is in the evidence. [NVD-CVE-2021-44228] "
            "Recommendations: not executed; human approval required. [CISA-KEV]"
        },
    )
    assert valid is not None
    assert valid_metadata["fallback"] is False
    assert valid_metadata["prompt_version"] == "security-triage-report/v2"


def test_model_comparison_uses_same_evidence_and_records_failures():
    from react_agent.apps.security_triage.llm_report import compare_report_models

    case = _triage({"cve_ids": ["CVE-2021-44228"]})["case"]
    comparison = compare_report_models(
        case,
        {
            "candidate-good": lambda prompt, evidence: {
                "content": "Findings [NVD-CVE-2021-44228]. Recommendations: not executed [CISA-KEV]."
            },
            "candidate-bad": lambda prompt, evidence: {"content": "unsafe unsupported claim [FAKE]"},
        },
    )
    assert comparison["schema_version"] == "security-triage-model-comparison/v1"
    assert comparison["candidate_count"] == 2
    assert comparison["valid_count"] == 1
    assert comparison["results"][0]["prompt_version"] == "security-triage-report/v2"
    assert comparison["results"][1]["failure"].startswith("unknown_citation_ids")


def test_structured_json_repair_adds_citations_without_changing_fact():
    from react_agent.apps.security_triage.llm_report import generate_llm_report

    case = _triage({"cve_ids": ["CVE-2021-44228"]})["case"]
    responses = iter(
        [
            {
                "content": json.dumps(
                    {
                        "claims": [{"text": "CVE-2021-44228 is critical", "type": "fact", "citation_ids": []}],
                        "recommendations": [],
                        "limitations": ["Review required"],
                    }
                )
            },
            {
                "content": json.dumps(
                    {
                        "claims": [{"text": "CVE-2021-44228 is critical", "type": "fact", "citation_ids": ["NVD-CVE-2021-44228"]}],
                        "recommendations": [{"text": "Confirm asset scope", "citation_ids": ["CISA-KEV"], "execution": "not_executed", "requires_human_approval": True}],
                        "limitations": ["Review required"],
                    }
                )
            },
        ]
    )
    output, metadata = generate_llm_report(case, chat=lambda prompt, evidence: next(responses))
    assert output is not None
    assert "CVE-2021-44228 is critical" in output
    assert "[NVD-CVE-2021-44228]" in output
    assert metadata["attempts"] == 2
    assert metadata["repair_used"] is True
    assert metadata["output_format"] == "json"


def test_structured_repair_rejects_changed_factual_claims():
    from react_agent.apps.security_triage.llm_report import generate_llm_report

    case = _triage({"cve_ids": ["CVE-2021-44228"]})["case"]
    responses = iter(
        [
            {"content": json.dumps({"claims": [{"text": "Original fact", "type": "fact", "citation_ids": []}], "recommendations": [], "limitations": ["Review required"]})},
            {"content": json.dumps({"claims": [{"text": "Changed fact", "type": "fact", "citation_ids": ["NVD-CVE-2021-44228"]}], "recommendations": [], "limitations": ["Review required"]})},
        ]
    )
    output, metadata = generate_llm_report(case, chat=lambda prompt, evidence: next(responses))
    assert output is None
    assert metadata["failure"] == "repair_changed_factual_claims"


def test_security_skill_is_read_only_and_verified():
    from react_agent.skills import get_skill, run_skill

    skill = get_skill("security_triage")
    assert skill.risk_level == "read_only"
    assert set(skill.allowed_tools) == {
        "security_lookup_cve",
        "security_check_kev",
        "security_triage_report",
    }
    result = run_skill("security_triage", {"cve_ids": ["CVE-2021-44228"]})
    assert result.ok is True
    assert result.checks["no_actions_executed"] is True


def test_security_golden_eval_and_replay(tmp_path):
    import runpy

    from react_agent.apps.security_triage.replay import load_replays, replay_record

    dataset = "react-agent/examples/fixtures/security_triage_goldens.json"
    replay_path = tmp_path / "security.jsonl"
    episodes_path = tmp_path / "episodes.jsonl"
    run = runpy.run_path("react-agent/examples/eval/run_security_triage_eval.py")["run"]
    metrics = run(dataset, str(replay_path), str(episodes_path))
    assert metrics["cases"] == 36
    assert metrics["passed"] == 36
    assert metrics["false_safe_assertions"] == 0
    records = load_replays(replay_path)
    assert len(records) == 36
    from react_agent.apps.security_triage.episode import load_evaluation_episodes

    episodes = load_evaluation_episodes(episodes_path)
    assert len(episodes) == 36
    assert all(item["schema_version"] == "evaluation-episode/v1" for item in episodes)
    assert all(item["state_verification"]["passed"] for item in episodes)
    assert episodes[0]["expected_state"]["security"]["priority"] == "critical"
    replayed = replay_record(records[0])
    assert replayed["case"]["schema_version"] == "security-triage/v1"


def test_router_and_application_registry():
    from react_agent.server.chat_router import handle_chat, list_applications

    status, payload = handle_chat(
        {"app": "security", "message": "研判 CVE-2021-44228 和 example.invalid"},
        "request-security-1",
    )
    assert status == 200
    assert payload["request_id"] == "request-security-1"
    assert payload["app"] == "security_triage"
    assert payload["case"]["status"] == "pending_review"
    assert "security_triage" in {item["id"] for item in list_applications()}


def test_stdlib_http_route():
    from react_agent.server.app import AgentHandler

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), AgentHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{httpd.server_address[1]}/v1/chat",
            data=json.dumps(
                {"app": "security_triage", "cve_ids": ["CVE-2021-44228"], "message": "triage"}
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert payload["app"] == "security_triage"
        assert payload["case"]["kev"][0]["listed"] is True
    finally:
        httpd.shutdown()


@pytest.mark.anyio
async def test_fastapi_chat_and_sqlalchemy_durable_task(tmp_path):
    httpx = pytest.importorskip("httpx")
    pytest.importorskip("fastapi")
    pytest.importorskip("sqlalchemy")

    from react_agent.server.fastapi_app import create_app
    from react_agent.server.sqlalchemy_store import SQLAlchemyTaskStore
    from react_agent.server.task_manager import TaskManager

    database_url = f"sqlite:///{tmp_path / 'security_tasks.db'}"
    store = SQLAlchemyTaskStore(database_url)
    manager = TaskManager(max_workers=1, store=store)
    api = create_app(manager=manager, initialize_runtime=False)
    request_body = {
        "app": "security_triage",
        "message": "研判 CVE-2021-44228 和 example.invalid",
        "cve_ids": ["CVE-2021-44228"],
        "iocs": ["example.invalid"],
    }
    try:
        transport = httpx.ASGITransport(app=api)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            chat = await client.post("/v1/chat", json=request_body)
            assert chat.status_code == 200
            assert chat.json()["case"]["status"] == "pending_review"

            submitted = await client.post("/v1/tasks", json=request_body)
            assert submitted.status_code == 202
            task_id = submitted.json()["task_id"]
            terminal = None
            for _ in range(100):
                task = await client.get(f"/v1/tasks/{task_id}")
                terminal = task.json()
                if terminal["status"] in {"succeeded", "failed", "cancelled"}:
                    break
                await asyncio.sleep(0.01)
            assert terminal is not None
            assert terminal["status"] == "succeeded"
            assert terminal["result"]["payload"]["case"]["kev"][0]["listed"] is True

        restored_store = SQLAlchemyTaskStore(database_url)
        try:
            restored = restored_store.get(task_id)
            assert restored is not None
            assert restored.status == "succeeded"
            assert restored.result["payload"]["app"] == "security_triage"
        finally:
            restored_store.close()
    finally:
        manager.shutdown()
        store.close()


@pytest.mark.anyio
async def test_persistent_case_asset_review_and_optimistic_lock(tmp_path):
    httpx = pytest.importorskip("httpx")
    pytest.importorskip("fastapi")
    pytest.importorskip("sqlalchemy")

    from react_agent.apps.security_triage.case_store import SecurityCaseStore
    from react_agent.server.fastapi_app import create_app

    database_url = f"sqlite:///{tmp_path / 'triage_cases.db'}"
    case_store = SecurityCaseStore(database_url)
    api = create_app(initialize_runtime=False, security_case_store=case_store)
    body = {
        "message": "研判 CVE-2021-44228",
        "cve_ids": ["CVE-2021-44228"],
        "assets": [
            {
                "asset_id": "edge-api-01",
                "criticality": "critical",
                "internet_exposed": True,
                "components": [
                    {
                        "name": "log4j-core",
                        "version": "2.14.1",
                        "cve_ids": ["CVE-2021-44228"],
                    }
                ],
            }
        ],
    }
    try:
        transport = httpx.ASGITransport(app=api)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            missing = await client.get("/v1/security/cases/missing")
            assert missing.status_code == 404

            created = await client.post(
                "/v1/security/cases",
                json=body,
                headers={"X-Request-Id": "security-create-1"},
            )
            assert created.status_code == 201
            record = created.json()
            case_id = record["case_id"]
            assert record["request_id"] == "security-create-1"
            assert record["version"] == 1
            assert record["status"] == "pending_review"
            assert record["case"]["asset_matches"][0]["matched"] is True
            assert record["case"]["recommendations"][0]["priority"] == "critical"

            fetched = await client.get(f"/v1/security/cases/{case_id}")
            assert fetched.status_code == 200
            assert fetched.json()["case_id"] == case_id

            approved = await client.post(
                f"/v1/security/cases/{case_id}/reviews",
                json={
                    "decision": "approve",
                    "reviewer": "analyst-01",
                    "notes": "资产和 SBOM 已复核",
                    "expected_version": 1,
                },
            )
            assert approved.status_code == 200
            assert approved.json()["status"] == "approved"
            assert approved.json()["version"] == 2
            assert approved.json()["case"]["executed_actions"] == []

            stale = await client.post(
                f"/v1/security/cases/{case_id}/reviews",
                json={
                    "decision": "reject",
                    "reviewer": "analyst-02",
                    "expected_version": 1,
                },
            )
            assert stale.status_code == 409
            assert stale.json()["error"]["code"] == "case_version_conflict"

            history = await client.get(f"/v1/security/cases/{case_id}/reviews")
            assert history.status_code == 200
            assert len(history.json()["reviews"]) == 1
            assert history.json()["reviews"][0]["reviewer"] == "analyst-01"

            schema = (await client.get("/openapi.json")).json()
            assert "/v1/security/cases" in schema["paths"]
            assert "/v1/security/cases/{case_id}/reviews" in schema["paths"]

        reopened = SecurityCaseStore(database_url)
        try:
            restored = reopened.get(case_id)
            assert restored is not None
            assert restored["status"] == "approved"
            assert restored["version"] == 2
        finally:
            reopened.close()
    finally:
        case_store.close()
