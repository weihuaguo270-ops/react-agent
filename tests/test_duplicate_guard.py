"""Flywheel helpers: normalize + offtrack unit checks"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

os.environ["REACT_AGENT_SKIP_RAG"] = "1"


def test_normalize_tool_args():
    from react_agent.react_loop import _normalize_tool_args

    a = _normalize_tool_args('{"b": 2, "a": 1}')
    b = _normalize_tool_args('{"a": 1, "b": 2}')
    assert a == b
    assert _normalize_tool_args('{"url": "x"}') != _normalize_tool_args('{"url": "y"}')
