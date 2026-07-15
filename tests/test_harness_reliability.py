"""Harness 长跑可靠性：自修启发式 + ToolGuard 默认接通冒烟"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

os.environ["REACT_AGENT_SKIP_RAG"] = "1"
os.environ["REACT_AGENT_SANDBOX_PREWARM"] = "0"


def test_looks_like_tool_error():
    from react_agent.react_loop import looks_like_tool_error, self_repair_hint

    assert looks_like_tool_error('{"error": "超时 (30s)"}')
    assert looks_like_tool_error("[错误] 代码执行超时")
    assert not looks_like_tool_error("323")
    hint = self_repair_hint("calculator", '{"error": "x"}')
    assert "[Harness自修]" in hint
    assert "calculator" in hint


def test_tool_guard_wraps_execute():
    """默认开 Guard 时，畸形调用应被阻断而非抛异常。"""
    os.environ["REACT_AGENT_TOOL_GUARD"] = "1"
    # 强制重新接线
    import react_agent.react_loop as loop
    loop._GUARDED_EXECUTE = None
    loop._TOOL_GUARD = None
    out = loop.execute_tool_call({"bad": True})
    data = json.loads(out)
    assert data.get("blocked") is True or "畸形" in out


def test_resolve_max_steps_env():
    from react_agent.react_loop import _resolve_max_steps

    os.environ["REACT_AGENT_MAX_STEPS"] = "7"
    assert _resolve_max_steps(None) == 7
    assert _resolve_max_steps(3) == 3
    os.environ.pop("REACT_AGENT_MAX_STEPS", None)
    assert _resolve_max_steps(None) == 10
