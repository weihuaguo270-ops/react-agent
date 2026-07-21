#!/usr/bin/env python3
"""Framework path demo — StateGraph + MemorySaver + HITL（无需 API Key）。

对照 Core ``react_loop``（互补，不是互相取代）:

1. **显式图编排**: ``propose → gate → act → END``，条件边决定是否过人工闸门
2. **Checkpointer**: 同一 ``thread_id`` 跨轮续跑，``get_state`` 可读检查点
3. **HITL**: CONFIRM 级工具在 gate 节点拦截；脚本化审批，便于无 Key 演示

安装与运行::

    pip install -e ".[langgraph]"
    python experiments/langgraph/demo_checkpoint_hitl.py

完整 Agent（需 Key）仍走 ``experiments/langgraph/graph/main.py``。
"""
from __future__ import annotations

import sys
from typing import Annotated, Literal, TypedDict

try:
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import END, StateGraph
except ImportError:
    print(
        "缺少 LangGraph。请先安装可选依赖:\n"
        "  pip install -e \".[langgraph]\"\n"
    )
    sys.exit(1)


class DemoState(TypedDict):
    messages: Annotated[list[str], lambda a, b: a + b]
    pending_tool: str
    pending_args: dict
    approved: bool
    observation: str
    turn: int


def _build_app(*, auto_approve: bool = False):
    """构建最小对照图（确定性节点，不调 LLM）。"""

    def propose(state: DemoState) -> dict:
        turn = int(state.get("turn") or 0) + 1
        # 第 1 轮：高风险工具（需 HITL）；第 2 轮：安全工具（自动放行）
        if turn == 1:
            tool, args = "execute_python", {"code": "print(1+1)"}
        else:
            tool, args = "calculator", {"expression": "2+2"}
        return {
            "turn": turn,
            "pending_tool": tool,
            "pending_args": args,
            "approved": False,
            "observation": "",
            "messages": [f"turn={turn} propose tool={tool}"],
        }

    def gate(state: DemoState) -> dict:
        tool = state.get("pending_tool") or ""
        # CONFIRM 级：execute_python；SAFE：calculator
        needs_hitl = tool in ("execute_python", "write_file", "delete_file")
        if not needs_hitl:
            return {
                "approved": True,
                "messages": [f"gate: {tool} is SAFE -> auto-approve"],
            }
        if auto_approve:
            return {
                "approved": True,
                "messages": [f"gate: HITL auto_approve={tool}"],
            }
        # 演示默认：拒绝高风险，体现闸门生效（面试可改 True 对比）
        return {
            "approved": False,
            "messages": [f"gate: HITL DENY {tool} (demo default)"],
        }

    def route_after_gate(state: DemoState) -> Literal["act", "blocked"]:
        return "act" if state.get("approved") else "blocked"

    def act(state: DemoState) -> dict:
        tool = state.get("pending_tool") or ""
        args = state.get("pending_args") or {}
        if tool == "calculator":
            obs = "4"
        elif tool == "execute_python":
            obs = "2"
        else:
            obs = f"ok:{tool}"
        return {
            "observation": obs,
            "messages": [f"act: ran {tool}({args}) -> {obs}"],
        }

    def blocked(state: DemoState) -> dict:
        tool = state.get("pending_tool") or ""
        return {
            "observation": f"blocked:{tool}",
            "messages": [f"blocked: user denied {tool}"],
        }

    g = StateGraph(DemoState)
    g.add_node("propose", propose)
    g.add_node("gate", gate)
    g.add_node("act", act)
    g.add_node("blocked", blocked)
    g.set_entry_point("propose")
    g.add_edge("propose", "gate")
    g.add_conditional_edges(
        "gate",
        route_after_gate,
        {"act": "act", "blocked": "blocked"},
    )
    g.add_edge("act", END)
    g.add_edge("blocked", END)
    return g.compile(checkpointer=MemorySaver())


def main() -> int:
    print("=" * 60)
    print(" LangGraph demo: StateGraph + Checkpoint + HITL")
    print(" (no API key; deterministic nodes)")
    print("=" * 60)

    app = _build_app(auto_approve=False)
    thread = "interview-demo-thread"
    config = {"configurable": {"thread_id": thread}}

    # ── Turn 1: HITL 拒绝高风险工具 ──
    r1 = app.invoke(
        {
            "messages": [],
            "pending_tool": "",
            "pending_args": {},
            "approved": False,
            "observation": "",
            "turn": 0,
        },
        config,
    )
    print("\n[Turn 1] high-risk tool -> HITL DENY")
    print(f"  pending_tool = {r1.get('pending_tool')}")
    print(f"  observation  = {r1.get('observation')}")
    print(f"  messages     = {r1.get('messages')}")

    snap1 = app.get_state(config)
    print(f"  checkpoint turn = {snap1.values.get('turn')}")

    # ── Turn 2: 同 thread 续跑；SAFE 工具自动放行 ──
    # 只更新 turn 相关：图从 entry 再跑，但 checkpointer 保留历史 messages
    r2 = app.invoke(
        {
            "messages": [],
            "pending_tool": "",
            "pending_args": {},
            "approved": False,
            "observation": "",
            "turn": snap1.values.get("turn", 1),
        },
        config,
    )
    print("\n[Turn 2] same thread_id -> SAFE tool auto-approve")
    print(f"  pending_tool = {r2.get('pending_tool')}")
    print(f"  observation  = {r2.get('observation')}")
    print(f"  messages     = {r2.get('messages')}")

    snap2 = app.get_state(config)
    print(f"  checkpoint turn = {snap2.values.get('turn')}")
    print(f"  checkpoint msgs = {len(snap2.values.get('messages') or [])} entries")

    print("\n" + "-" * 60)
    print("Interview talking points:")
    print("  - Core path: procedural loop makes control flow obvious")
    print("  - Framework path: edges + checkpointer + gate node")
    print("  - Same concerns (tools/failure/HITL/traces), different layering")
    print("  - Choose by team/ops needs — not by 'handwritten = better'")
    print("-" * 60)
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
