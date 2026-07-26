"""Offline demo: Context truncate / summarize / drop（无需 API Key）。

用法:
  python examples/demo_context.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from react_agent.context import ContextManager, ContextStrategy, estimate_messages_tokens


def _pad_history(n: int = 14):
    pad = "上下文窗口压力测试内容。" * 40
    msgs = [{"role": "system", "content": "你是报销助手。"}]
    for i in range(n):
        msgs.append({"role": "user", "content": f"第{i}轮问题 {pad}"})
        msgs.append({"role": "assistant", "content": f"第{i}轮回答 {pad}"})
    return msgs


def main():
    msgs = _pad_history()
    print(f"原始 messages={len(msgs)} tokens≈{estimate_messages_tokens(msgs)}")

    # drop：短历史 + 超大 tool 结果，丢掉 tool 对后即可回到限额内
    drop_msgs = [
        {"role": "system", "content": "你是报销助手。"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "t1", "function": {"name": "rag_query", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "t1", "content": ("政策片段 " * 400)},
        {"role": "user", "content": "根据政策判断能否报销"},
        {"role": "assistant", "content": "需要发票与额度信息"},
    ]

    cases = [
        ("truncate", ContextStrategy.TRUNCATE, 1200, msgs, None),
        ("summarize", ContextStrategy.SUMMARIZE, 2500, msgs,
         lambda p: "[摘要] 多轮报销问答已压缩。"),
        ("drop", ContextStrategy.DROP, 500, drop_msgs, None),
    ]
    for name, strategy, limit, seed, llm in cases:
        cm = ContextManager(max_tokens=limit, reserve_tokens=40, strategy=strategy)
        copy = [dict(m) for m in seed]
        out = cm.manage(copy, llm_call=llm) if llm else cm.manage(copy)
        print(
            f"[{name}] -> messages={len(out)} tokens~{estimate_messages_tokens(out)} "
            f"| {cm.last_action or 'ok'}"
        )

    print("\n说明: react_loop 每步结束会调用 CONTEXT.manage(..., llm_call=_context_llm_wrapper)，")
    print("      summarize/auto 不再静默退化成 truncate（有可用 LLM 时）。")


if __name__ == "__main__":
    main()
