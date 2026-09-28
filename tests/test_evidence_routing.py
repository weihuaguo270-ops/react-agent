from __future__ import annotations

import json

from react_agent.apps.docs_troubleshoot.agent_runner import decide_next_tool
from react_agent.apps.docs_troubleshoot.prompt import get_system_prompt


def test_general_question_does_not_force_internal_retrieval():
    assert decide_next_tool({"query": "法国首都是什么？"}, set()) is None
    prompt = get_system_prompt("法国首都是什么？")
    assert "普通常识问答不必强制检索" in prompt


def test_api_or_log_question_still_starts_with_evidence_retrieval():
    _, tool, _ = decide_next_tool({"query": "API 返回 401 如何排障？"}, set())
    assert tool == "search_docs"
    _, tool, _ = decide_next_tool({"query": "服务不可用", "log_excerpt": "trace_id=abc"}, set())
    assert tool == "parse_log_evidence"
