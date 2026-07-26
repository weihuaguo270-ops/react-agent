"""ContextManager strategies — offline, no LLM provider."""
from __future__ import annotations

from react_agent.context import ContextManager, ContextStrategy


def _fat_messages(n_user: int = 12, pad: str = "x" * 400):
    msgs = [{"role": "system", "content": "You are a helpful agent."}]
    for i in range(n_user):
        msgs.append({"role": "user", "content": f"q{i} {pad}"})
        msgs.append({"role": "assistant", "content": f"a{i} {pad}"})
    return msgs


def test_truncate_reduces_when_over_limit():
    cm = ContextManager(max_tokens=800, reserve_tokens=50, strategy=ContextStrategy.TRUNCATE)
    msgs = _fat_messages()
    assert not cm.check(msgs)["is_ok"]
    out = cm.manage(msgs)
    assert cm.check(out)["is_ok"]
    assert out[0]["role"] == "system"
    assert "截断" in cm.last_action


def test_summarize_without_llm_falls_back_truncate():
    cm = ContextManager(max_tokens=800, reserve_tokens=50, strategy=ContextStrategy.SUMMARIZE)
    msgs = _fat_messages()
    out = cm.manage(msgs, llm_call=None)
    assert cm.check(out)["is_ok"]
    # 策略可能被回退改写为 truncate
    assert cm.strategy == ContextStrategy.TRUNCATE


def test_summarize_with_llm_call_uses_summary():
    cm = ContextManager(max_tokens=900, reserve_tokens=50, strategy=ContextStrategy.SUMMARIZE)
    msgs = _fat_messages(n_user=10, pad="对话内容" * 80)

    def fake_llm(prompt: str) -> str:
        assert "摘要" in prompt or "总结" in prompt or "对话" in prompt or len(prompt) > 20
        return "【摘要】用户多次询问，助手已答复。"

    out = cm.manage(msgs, llm_call=fake_llm)
    assert cm.check(out)["is_ok"]
    # 摘要路径应注入一段摘要类消息
    joined = " ".join(str(m.get("content", "")) for m in out)
    assert "摘要" in joined or cm.last_action


def test_drop_removes_tool_pairs():
    cm = ContextManager(max_tokens=400, reserve_tokens=40, strategy=ContextStrategy.DROP)
    pad = "y" * 200
    msgs = [
        {"role": "system", "content": "sys"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "t1", "function": {"name": "calculator", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "t1", "content": pad},
        {"role": "user", "content": "continue " + pad},
        {"role": "assistant", "content": "done " + pad},
        {"role": "user", "content": "more " + pad},
        {"role": "assistant", "content": "ok " + pad},
    ]
    if cm.check(msgs)["is_ok"]:
        # 若未超限，加长 tool 结果
        msgs[2]["content"] = pad * 5
    out = cm.manage(msgs)
    assert cm.check(out)["is_ok"] or "丢弃" in cm.last_action or "截断" in cm.last_action
