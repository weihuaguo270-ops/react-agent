"""Opt-in real DeepSeek call through the LangGraph agent path."""
from __future__ import annotations

import os
import sys
from pathlib import Path
import uuid

import pytest


pytestmark = [pytest.mark.real_llm, pytest.mark.real_llm_smoke]


def test_langgraph_deepseek_smoke():
    if not os.environ.get("DEEPSEEK_API_KEY"):
        pytest.skip("需要 DEEPSEEK_API_KEY")
    pytest.importorskip("langgraph")
    pytest.importorskip("langchain_openai")

    graph_dir = Path(__file__).resolve().parents[1] / "experiments" / "langgraph" / "graph"
    sys.path.insert(0, str(graph_dir))
    try:
        from agent import run

        answer = run(
            "请只回答数字 2，不要调用工具。",
            max_steps=3,
            thread_id=f"real-llm-{uuid.uuid4().hex}",
        )
    finally:
        sys.path.remove(str(graph_dir))

    assert answer.strip(), "LangGraph Provider 返回空答案"
    assert "LLM调用失败" not in answer
    assert "HTTP Error 401" not in answer
