"""Business Skill routing and workflow-boundary tests."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from react_agent.skills import (
    SkillRoutingError,
    list_skills,
    get_skill_context,
    route_skill,
    route_skill_decision,
    run_skill_pipeline,
    run_skill,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _repository(tmp_path: Path) -> Path:
    repo = tmp_path / "service"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "skill-test")
    _git(repo, "config", "user.email", "skill-test@example.com")
    (repo / "service.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "test_service.py").write_text(
        "from service import VALUE\n\ndef test_value():\n    assert VALUE == 2\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture")
    return repo


def test_skill_catalog_is_split_by_business_scenario():
    catalog = {item["name"]: item for item in list_skills()}
    assert set(catalog) == {
        "docs_troubleshoot",
        "expense_claim_review",
        "github_delivery",
        "security_triage",
    }
    assert catalog["docs_troubleshoot"]["workflow"] == "docs_troubleshoot@5"
    assert catalog["expense_claim_review"]["scenario"] == "expense_approval"
    assert catalog["github_delivery"]["agent_callable"] is False
    assert catalog["github_delivery"]["risk_level"] == "external_write"
    assert catalog["security_triage"]["risk_level"] == "read_only"


def test_router_uses_structured_business_signals_without_llm():
    assert route_skill("API 401 怎么排障").name == "docs_troubleshoot"
    assert route_skill("这张报销单需要谁审批？").name == "expense_claim_review"
    assert route_skill("研判 CVE-2021-44228 是否在 KEV").name == "security_triage"
    assert route_skill(
        payload={
            "repository": "repo",
            "replacements": [],
            "test_command": [],
            "acceptance_criteria": [],
        }
    ).name == "github_delivery"
    with pytest.raises(SkillRoutingError, match="no business skill"):
        route_skill("写一首诗")


def test_route_decision_reports_confidence_and_explicit_selector():
    decision = route_skill_decision("401", {"app": "technical_support"})
    assert decision.skill == "docs_troubleshoot"
    assert decision.reason == "explicit selector"
    assert decision.confidence == 1.0


def test_progressive_disclosure_hides_deep_context_until_requested():
    summary = get_skill_context("docs_troubleshoot", level="summary")
    assert "instructions" not in summary
    assert "allowed_tools" not in summary
    full = get_skill_context("docs_troubleshoot", level="full")
    assert full["instructions"]
    assert full["allowed_tools"]
    assert full["input_schema"]["required"] == ["query"]


def test_missing_required_input_fails_closed():
    result = run_skill("docs_troubleshoot", {})
    assert result.ok is False
    assert result.checks == {"required_inputs": False}
    assert "query" in result.error


def test_schema_validation_rejects_wrong_nested_type():
    result = run_skill(
        "expense_claim_review",
        {"claim": {"category": "交通", "amount": "80", "has_receipt": True}},
    )
    assert result.ok is False
    assert result.checks == {"input_schema": False}
    assert "amount" in result.error


def test_docs_skill_runs_workflow_and_verifies_release_contract(monkeypatch):
    monkeypatch.setenv("REACT_AGENT_RAG_MODE", "keyword")
    from react_agent.apps.docs_troubleshoot.index import reset_index

    reset_index()
    result = run_skill(
        "docs_troubleshoot",
        {"query": "缺少 Authorization 返回什么？"},
    )
    assert result.ok, result.to_dict()
    assert result.output["workflow"] == "docs_troubleshoot"
    assert result.output["policy"] == "ok"
    assert result.output["citations"]
    assert result.checks["citations_verified_or_refused"] is True
    assert "401" in result.output["answer"] or "unauthorized" in result.output["answer"].lower()


def test_expense_skill_uses_deterministic_rule_engine(monkeypatch):
    monkeypatch.setenv("REACT_AGENT_RAG_MODE", "keyword")
    result = run_skill(
        "expense_claim_review",
        {
            "claim": {
                "category": "交通",
                "amount": 80,
                "has_receipt": False,
            }
        },
    )
    assert result.ok, result.to_dict()
    assert result.output["decision"] == "reject_no_receipt"
    assert result.output["refused"] is True
    assert result.checks["deterministic_decision"] is True


def test_agent_tool_cannot_start_external_write_skill():
    from react_agent.skills.tools import run_business_skill_tool

    payload = json.loads(run_business_skill_tool("github_delivery"))
    assert payload["ok"] is False
    assert payload["risk_level"] == "external_write"
    assert "explicit controlled caller" in payload["error"]


def test_tool_allowlist_blocks_direct_runtime_call():
    from react_agent.react_loop import execute_tool_call

    raw = execute_tool_call(
        {"function": {"name": "calculator", "arguments": '{"expression":"1+1"}'}},
        allowed_tools={"search_docs"},
    )
    payload = json.loads(raw)
    assert payload["error"] == "skill_tool_not_allowed"
    assert payload["tool"] == "calculator"


def test_react_loop_injects_summary_and_enforces_skill_tool_scope(monkeypatch):
    import react_agent.react_loop as loop

    monkeypatch.setenv("REACT_AGENT_APP", "docs_troubleshoot")
    monkeypatch.setenv("REACT_AGENT_SKIP_RAG", "1")

    class FakeLLM:
        provider_name = "ollama"
        api_key = ""
        model = "fake-skill-model"

    calls = []

    def fake_call(messages, *, tool_defs=None, **_):
        calls.append({"messages": messages, "tool_defs": tool_defs or []})
        if len(calls) == 1:
            return {
                "role": "assistant",
                "content": "THOUGHT: try an unlisted tool",
                "tool_calls": [
                    {
                        "id": "tc-1",
                        "type": "function",
                        "function": {
                            "name": "calculator",
                            "arguments": '{"expression":"1+1"}',
                        },
                    }
                ],
            }
        return {"role": "assistant", "content": "FINAL ANSWER: blocked"}

    monkeypatch.setattr(loop, "_active_llm", lambda: FakeLLM())
    monkeypatch.setattr(loop, "call_llm", fake_call)
    answer = loop.react_loop("API 401 怎么排障", max_steps=2)

    assert answer == "blocked"
    assert calls[0]["tool_defs"]
    names = {item["function"]["name"] for item in calls[0]["tool_defs"]}
    assert "calculator" not in names
    assert "search_docs" in names
    system_prompt = calls[0]["messages"][0]["content"]
    assert "当前业务 Skill 摘要" in system_prompt
    assert "allowed_tools" not in system_prompt
    assert "skill_tool_not_allowed" in str(loop.last_trajectory_steps)


def test_skill_pipeline_carries_output_and_stops_on_contract_failure():
    result = run_skill_pipeline(
        ["expense_claim_review", "docs_troubleshoot"],
        {"claim": {"category": "交通", "amount": 80, "has_receipt": True}},
    )
    assert result.ok is False
    assert result.failed_at == "docs_troubleshoot"
    assert len(result.results) == 2
    assert result.results[0].ok is True
    assert result.results[1].checks == {"required_inputs": False}


def test_github_skill_runs_shadow_workflow_without_modifying_source(tmp_path):
    repo = _repository(tmp_path)
    result = run_skill(
        "github_delivery",
        {
            "task_id": "skill-issue-1",
            "repository": str(repo),
            "issue_url": "local://issues/skill-1",
            "split": "dev",
            "replacements": [
                {"path": "service.py", "old": "VALUE = 1", "new": "VALUE = 2"}
            ],
            "test_command": ["python", "-m", "pytest", "-q"],
            "acceptance_criteria": ["tests pass", "source remains unchanged"],
            "artifact_dir": str(tmp_path / "artifacts"),
            "idempotency_key": "skill-shadow-1",
            "mode": "shadow",
        },
    )
    assert result.ok, result.to_dict()
    assert result.output["status"] == "shadow_passed"
    assert result.output["metrics"]["unauthorized_external_write"] is False
    assert (repo / "service.py").read_text(encoding="utf-8") == "VALUE = 1\n"


def test_skill_tools_are_registered():
    from react_agent.tools import TOOL_REGISTRY

    assert "list_business_skills" in TOOL_REGISTRY
    assert "run_business_skill" in TOOL_REGISTRY
