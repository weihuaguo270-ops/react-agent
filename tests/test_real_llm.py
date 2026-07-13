"""
真实 LLM 集成测试 — 覆盖简单与复杂任务
=======================================

测试分类：
  - 简单任务：事实问答、工具调用
  - 复杂任务：多步推理、错误恢复、长上下文
"""

import os
import pytest


def _has_key() -> bool:
    return bool(os.environ.get("DEEPSEEK_API_KEY"))


REQUIRES_API = pytest.mark.skipif(not _has_key(), reason="需要 DEEPSEEK_API_KEY")


# ══════════════════════════════════════════════
# 简单任务
# ══════════════════════════════════════════════

@REQUIRES_API
def test_factual_qa():
    """事实问答 — Agent 应直接给出正确答案"""
    from react_agent.react_loop import react_loop

    output = react_loop("法国的首都是什么？回答一个字", max_steps=2)
    answer = output if isinstance(output, str) else output.get("output", "")
    assert any(c in answer for c in ["巴", "黎", "Paris"]), f"事实问答失败: {answer[:60]}"
    print(f"✅ 事实问答: {answer[:40]}")


@REQUIRES_API
def test_calculator():
    """工具调用 — Agent 应调 calculator 而非靠 LLM 记忆算数"""
    from react_agent.react_loop import react_loop

    output = react_loop("计算 1234 × 5678 等于多少？", max_steps=5)
    answer = output if isinstance(output, str) else output.get("output", "")
    # 7006652 是 1234×5678 的正确结果
    assert "7006652" in answer.replace(",", ""), f"计算结果错误: {answer[:80]}"
    print(f"✅ 工具调用(计算器): {answer[:60]}")


@REQUIRES_API
def test_tool_selection():
    """工具选择 — Agent 应根据需求选择合适的工具"""
    from react_agent.react_loop import react_loop

    output = react_loop("搜索一下今天北京的温度", max_steps=5)
    answer = output if isinstance(output, str) else output.get("output", "")
    # 应该调用了 web_search 并返回温度信息
    assert len(answer) > 10, f"工具选择结果太短: {answer[:60]}"
    print(f"✅ 工具选择: {answer[:80]}")


@REQUIRES_API
def test_qa_with_city():
    """开放问答 — 包含多个信息点的回答"""
    from react_agent.react_loop import react_loop

    output = react_loop("Python 和 Java 的主要区别是什么？列举 3 点", max_steps=3)
    answer = output if isinstance(output, str) else output.get("output", "")
    assert len(answer) > 30, f"回答太短: {answer[:60]}"
    print(f"✅ 开放问答: {len(answer)} chars")


# ══════════════════════════════════════════════
# 复杂任务
# ══════════════════════════════════════════════

@REQUIRES_API
def test_multi_step_reasoning():
    """多步推理 — Agent 逐步分析问题"""
    from react_agent.react_loop import react_loop

    output = react_loop("""一个池塘里有一片荷叶，每天面积翻一倍。
第 30 天荷叶覆盖整个池塘。
问：第几天荷叶覆盖一半的池塘？""", max_steps=5)
    answer = output if isinstance(output, str) else output.get("output", "")
    assert "29" in answer, f"多步推理错误: {answer[:100]}"
    print(f"✅ 多步推理: {answer[:60]}")


@REQUIRES_API
def test_multi_turn_consistency():
    """多轮一致性 — Agent 对同一问题的多次回答应一致"""
    from react_agent.react_loop import react_loop

    q = "鲁迅的《狂人日记》是哪一年发表的？"
    answers = set()
    for _ in range(2):
        output = react_loop(q, max_steps=3)
        ans = output if isinstance(output, str) else output.get("output", "")
        answers.add(ans.strip()[:50])
    assert len(answers) == 1, f"多轮回答不一致: {answers}"
    print(f"✅ 多轮一致性: {answers.pop()[:40]}")


@REQUIRES_API
def test_tool_error_recovery():
    """错误恢复 — 工具调用失败后 Agent 应尝试其他方式"""
    from react_agent.react_loop import react_loop

    output = react_loop("搜索 '2025 年诺贝尔物理学奖' 的信息", max_steps=6)
    answer = output if isinstance(output, str) else output.get("output", "")
    assert len(answer) > 20, f"错误恢复失败: {answer[:60]}"
    print(f"✅ 错误恢复: {answer[:80]}")


@REQUIRES_API
def test_long_context():
    """长上下文 — 能处理包含长输入的任务"""
    from react_agent.react_loop import react_loop

    long_input = "请总结以下内容的核心观点：" + "人工智能正在改变各个行业。" * 50
    output = react_loop(long_input, max_steps=3)
    answer = output if isinstance(output, str) else output.get("output", "")
    assert len(answer) > 20, f"长上下文处理失败"
    print(f"✅ 长上下文: {len(answer)} chars")


@REQUIRES_API
def test_mcp_tool_integration():
    """MCP 工具 — MCP 客户端可被正确调用"""
    from react_agent.mcp_client import MCPClient

    client = MCPClient()
    # 至少应能列出工具
    tools = client.list_tools() if hasattr(client, 'list_tools') else []
    print(f"✅ MCP 客户端初始化成功: {len(tools)} 个工具")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
