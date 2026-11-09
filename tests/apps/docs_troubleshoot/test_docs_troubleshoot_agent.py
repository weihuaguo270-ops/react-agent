"""Agent-loop path for docs_troubleshoot."""
from __future__ import annotations

import json
import os
from pathlib import Path

os.environ["REACT_AGENT_APP"] = "docs_troubleshoot"
os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")
os.environ["REACT_AGENT_DOCS_ENGINE"] = "agent"


def test_agent_loop_records_tool_steps():
    from react_agent.apps.docs_troubleshoot.agent_runner import run_docs_agent
    from react_agent.apps.docs_troubleshoot.index import reset_index
    from react_agent.harness.recorder import TRAJECTORY_DIR

    reset_index()
    query = "缺少 Authorization 返回什么？"
    result = run_docs_agent({"query": query})
    assert result.ok
    assert result.trajectory_id
    actions = [s.get("action") for s in result.agent_steps]
    assert "search_docs" in actions
    assert "verify_citations" in actions
    assert "401" in result.answer or "unauthorized" in result.answer.lower()

    trajectory_path = Path(TRAJECTORY_DIR) / f"traj_{result.trajectory_id}.json"
    assert trajectory_path.is_file()
    payload = json.loads(trajectory_path.read_text(encoding="utf-8"))
    assert payload["session_id"] == result.trajectory_id
    assert payload["query"] == query
    assert payload["final_answer"] == result.answer
    assert payload["steps"]


def test_agent_refuse_without_retrieval():
    from react_agent.apps.docs_troubleshoot.agent_runner import run_docs_agent
    from react_agent.apps.docs_troubleshoot.index import reset_index

    reset_index()
    result = run_docs_agent({"query": "我们公司股价明天多少？"})
    assert result.refused
    actions = [s.get("action") for s in result.agent_steps]
    assert "search_docs" not in actions


def test_agent_field_evidence_triggers_parse_tools():
    from react_agent.apps.docs_troubleshoot.agent_runner import run_docs_agent
    from react_agent.apps.docs_troubleshoot.index import reset_index

    reset_index()
    result = run_docs_agent(
        {
            "query": "网关超时怎么排查？",
            "log_excerpt": "upstream_timeout trace_id=tr-504 status=504",
        }
    )
    actions = [s.get("action") for s in result.agent_steps]
    assert "parse_log_evidence" in actions
    assert "search_docs" in actions
    diag = result.diagnosis or {}
    assert diag.get("phenomenon") or diag.get("candidate_causes") or result.answer

