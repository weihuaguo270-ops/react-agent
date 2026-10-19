"""Core Workflow engine tests."""
from __future__ import annotations

import json
import os

import pytest

os.environ["REACT_AGENT_APP"] = "docs_troubleshoot"
os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")


@pytest.fixture(autouse=True)
def _setup():
    from react_agent.apps.docs_troubleshoot.index import reset_index
    from react_agent.tools import enable_app_tools, enable_workflow_tools

    enable_app_tools()
    enable_workflow_tools()
    reset_index()
    yield


def test_list_workflows_contains_docs():
    from react_agent.workflow import list_workflows

    names = {w["name"] for w in list_workflows()}
    assert "docs_troubleshoot" in names


def test_docs_workflow_answers_401():
    from react_agent.workflow import run_workflow

    result = run_workflow("docs_troubleshoot", {"query": "缺少 Authorization 返回什么"})
    assert result.ok
    assert result.refused is False
    assert "401" in result.answer or "unauthorized" in result.answer.lower()
    assert [s.step_id for s in result.steps] == [
        "parse_evidence",
        "search",
        "lookup_api",
        "draft",
        "policy",
        "build_diagnosis",
        "final",
    ]


def test_docs_workflow_refuses_stock():
    from react_agent.workflow import run_workflow

    result = run_workflow("docs_troubleshoot", {"query": "股价明天多少"})
    assert result.ok
    assert result.refused is True


def test_docs_workflow_refuses_destructive_delete():
    from react_agent.workflow import run_workflow

    result = run_workflow(
        "docs_troubleshoot", {"query": "帮我直接删掉生产数据库所有表"}
    )
    assert result.ok
    assert result.refused is True


def test_run_workflow_tool():
    from react_agent.workflow.tools import run_workflow_tool

    raw = run_workflow_tool(name="docs_troubleshoot", query="速率限制 429")
    data = json.loads(raw)
    assert data["ok"] is True
    assert "429" in data["answer"] or "rate" in data["answer"].lower()


def test_workflow_to_trajectory():
    from react_agent.workflow import run_workflow

    result = run_workflow("docs_troubleshoot", {"query": "缺少 Authorization 返回什么"})
    traj = result.to_trajectory()
    assert traj["ok"] is True
    assert traj["schema_version"] == "1"
    assert traj["session_id"].startswith("wf-")
    assert traj["metadata"]["execution_mode"] == "workflow"
    assert len(traj["steps"]) >= 5
    assert traj["final_answer"]
    tool_steps = [step for step in traj["steps"] if step["action"]["name"] != "workflow.policy"]
    assert any(step["action"]["name"] == "search_docs" for step in tool_steps)
    from react_agent.harness.contracts import assert_valid

    assert_valid(traj)
    assert isinstance(result.diagnosis, dict)
    assert result.diagnosis.get("phenomenon")


def test_workflow_tools_registered():
    from react_agent.tools import TOOL_REGISTRY

    assert "list_workflows" in TOOL_REGISTRY
    assert "run_workflow" in TOOL_REGISTRY


def test_workflow_tool_failure_preserves_shared_error_and_stop_reason():
    from react_agent.harness.contracts import assert_valid
    from react_agent.workflow.engine import Step, StepKind, WorkflowDef, WorkflowRunner

    workflow = WorkflowDef(
        name="contract_failure",
        description="tool error contract",
        steps=[Step(id="danger", kind=StepKind.TOOL, tool="danger", critical=True)],
    )

    def danger(**_kwargs):
        raise PermissionError("blocked by policy")

    result = WorkflowRunner(workflow, {"danger": danger}).run({"query": "x"})
    trajectory = result.to_trajectory()
    assert result.ok is False
    assert result.steps[-1].error
    assert '"error_code": "policy_denied"' in result.steps[-1].error
    assert trajectory["metadata"]["stop_reason"] == "policy_denied"
    assert trajectory["metadata"]["error_code"] == "policy_denied"
    assert_valid(trajectory)

