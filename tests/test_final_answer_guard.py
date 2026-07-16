"""Regression: tool success on last step must still yield a final answer."""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ["REACT_AGENT_SKIP_RAG"] = "1"
os.environ["REACT_AGENT_TOOL_GUARD"] = "0"
os.environ["REACT_AGENT_SELF_REPAIR"] = "0"
os.environ["REACT_AGENT_BLOCK_DUPLICATE_TOOLS"] = "0"
os.environ["REACT_AGENT_RESERVE_FINAL_STEP"] = "1"


def _tool_msg(name: str = "web_search", args: str = '{"query":"beijing weather"}'):
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": name, "arguments": args},
            }
        ],
    }


def test_extract_final_answer():
    from react_agent.react_loop import _extract_final_answer

    assert _extract_final_answer("FINAL ANSWER: sunny") == "sunny"
    assert _extract_final_answer("no marker") is None


def test_last_step_tool_then_force_finalize_when_max_steps_1():
    """max_steps=1 调工具后必须强制总结出非空答案。"""
    import react_agent.react_loop as rl

    calls = {"n": 0}

    def fake_llm(messages, tool_defs=None, **kwargs):
        calls["n"] += 1
        # 第一次：要工具；强制总结：给 FINAL ANSWER
        if tool_defs == [] or (isinstance(tool_defs, list) and len(tool_defs) == 0):
            return {
                "role": "assistant",
                "content": "FINAL ANSWER: 北京今天晴，25°C",
            }
        return _tool_msg()

    mock_llm = MagicMock()
    mock_llm.provider_name = "deepseek"
    mock_llm.api_key = "test-key"
    mock_llm.model = "mock"

    with patch.object(rl, "_active_llm", return_value=mock_llm), patch.object(
        rl, "call_llm", side_effect=fake_llm
    ), patch.object(
        rl, "execute_tool_call", return_value="Beijing: sunny, 25C"
    ), patch.object(rl, "_ensure_rag_loaded"):
        answer = rl.react_loop("北京今天天气如何？", max_steps=1)

    assert answer and "25" in answer
    assert calls["n"] >= 2  # tool step + force finalize


def test_reserve_final_step_blocks_tools_on_last_step():
    """max_steps=2：第1步工具，第2步收尾禁止工具并给出答案。"""
    import react_agent.react_loop as rl

    seen_empty_tools = {"ok": False}

    def fake_llm(messages, tool_defs=None, **kwargs):
        # None means default TOOL_DEFINITIONS; [] means reserved final
        if tool_defs == []:
            seen_empty_tools["ok"] = True
            return {
                "role": "assistant",
                "content": "FINAL ANSWER: 晴，25度",
            }
        return _tool_msg()

    mock_llm = MagicMock()
    mock_llm.provider_name = "deepseek"
    mock_llm.api_key = "test-key"
    mock_llm.model = "mock"

    with patch.object(rl, "_active_llm", return_value=mock_llm), patch.object(
        rl, "call_llm", side_effect=fake_llm
    ), patch.object(
        rl, "execute_tool_call", return_value="sunny 25C"
    ), patch.object(rl, "_ensure_rag_loaded"):
        answer = rl.react_loop("北京天气", max_steps=2)

    assert seen_empty_tools["ok"] is True
    assert answer and ("25" in answer or "晴" in answer)


def test_force_finalize_when_loop_ends_without_answer():
    """禁用预留收尾时：步数用尽仍强制总结。"""
    import react_agent.react_loop as rl

    os.environ["REACT_AGENT_RESERVE_FINAL_STEP"] = "0"
    try:
        def fake_llm(messages, tool_defs=None, **kwargs):
            if tool_defs == []:
                return {
                    "role": "assistant",
                    "content": "FINAL ANSWER: recovered answer",
                }
            return _tool_msg(args='{"query":"q"}')

        mock_llm = MagicMock()
        mock_llm.provider_name = "deepseek"
        mock_llm.api_key = "test-key"
        mock_llm.model = "mock"

        with patch.object(rl, "_active_llm", return_value=mock_llm), patch.object(
            rl, "call_llm", side_effect=fake_llm
        ), patch.object(
            rl, "execute_tool_call", return_value="obs"
        ), patch.object(rl, "_ensure_rag_loaded"):
            # With reserve off and max_steps=1, tools then force finalize
            answer = rl.react_loop("q", max_steps=1)

        assert "recovered" in answer
    finally:
        os.environ["REACT_AGENT_RESERVE_FINAL_STEP"] = "1"
