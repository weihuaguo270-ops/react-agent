"""Offline LLM payload / DeepSeek model migration guards."""
from __future__ import annotations

from react_agent.llm import (
    LLM,
    _resolve_model_and_thinking,
    _sanitize_messages,
)
from react_agent.resilience import ErrorCategory, classify_error


def test_legacy_deepseek_chat_maps_to_v4_flash(monkeypatch):
    monkeypatch.delenv("LLM_THINKING", raising=False)
    model, thinking = _resolve_model_and_thinking("deepseek-chat")
    assert model == "deepseek-v4-flash"
    assert thinking == "disabled"


def test_legacy_deepseek_reasoner_enables_thinking(monkeypatch):
    monkeypatch.delenv("LLM_THINKING", raising=False)
    model, thinking = _resolve_model_and_thinking("deepseek-reasoner")
    assert model == "deepseek-v4-flash"
    assert thinking == "enabled"


def test_empty_tools_omitted_from_payload():
    llm = LLM.__new__(LLM)
    llm.model = "deepseek-v4-flash"
    llm.thinking = "disabled"
    llm.temperature = 0.1
    llm.max_tokens = 100
    payload = llm.build_payload(
        [{"role": "user", "content": "hi"}],
        tool_defs=[],
    )
    assert "tools" not in payload
    assert "tool_choice" not in payload
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["model"] == "deepseek-v4-flash"


def test_nonempty_tools_included():
    llm = LLM.__new__(LLM)
    llm.model = "deepseek-v4-flash"
    llm.thinking = "disabled"
    llm.temperature = 0.1
    llm.max_tokens = 100
    tools = [
        {
            "type": "function",
            "function": {
                "name": "calculator",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    payload = llm.build_payload(
        [{"role": "user", "content": "1+1"}], tool_defs=tools
    )
    assert payload["tools"] == tools
    assert payload["tool_choice"] == "auto"


def test_sanitize_keeps_reasoning_content():
    msgs = _sanitize_messages(
        [
            {
                "role": "assistant",
                "content": None,
                "reasoning_content": "step",
                "tool_calls": [{"id": "1"}],
            },
        ]
    )
    assert msgs[0]["reasoning_content"] == "step"
    assert msgs[0].get("content") is None  # has tool_calls, leave content


def test_http_400_is_not_retryable():
    assert (
        classify_error("LLM调用失败: HTTP Error 400: Bad Request")
        == ErrorCategory.VALIDATION
    )
