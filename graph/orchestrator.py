"""
LangGraph 多 Agent 编排 — supervisor 自带依赖分析

supervisor: 用 LLM 分解任务 + 分析依赖关系 → 输出带 depends_on 的 Task 列表
worker:     按依赖层级依次执行（同层并行、层层等待）
join:       合并结果
"""

from typing import TypedDict, List, Annotated
import operator
import sys
import os
import json
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo/
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))                  # graph/

from langgraph.graph import StateGraph, END
from langchain_core.messages import SystemMessage, HumanMessage
from concurrent.futures import ThreadPoolExecutor, as_completed

from llm import get_llm
from agent import build_agent
from tools import filter_tools


# ============================================================
# 构建隔离的 Worker
# ============================================================

def _build_isolated_worker(task_description: str):
    """
    根据子任务描述，构建只暴露相关工具的 Agent。
    
    例如"计算 23 * 47"的 Worker 只有 calculator 工具，
    "搜索 Python 教程"的 Worker 只有 web_search 工具。
    """
    from langgraph.graph import StateGraph, END, MessagesState
    from langgraph.checkpoint.memory import MemorySaver
    from langchain_core.messages import AIMessage, ToolMessage, SystemMessage, HumanMessage
    from llm import get_llm
    from tools import filter_tools
    import json
    from typing import Literal

    tools = filter_tools(task_description)
    llm = get_llm().bind_tools(tools)
    tool_map = {t.name: t for t in tools}

    def call_model(state):
        response = llm.invoke(state["messages"])
        return {"messages": [response]}

    def tools_node(state):
        last_msg = state["messages"][-1]
        results = []
        for tc in last_msg.tool_calls:
            name, args, tc_id = tc["name"], tc.get("args", {}), tc["id"]
            if name in tool_map:
                try:
                    content = str(tool_map[name].invoke(args))
                except Exception as e:
                    content = json.dumps({"error": f"执行错误: {e}"})
            else:
                content = json.dumps({"error": f"未知工具: {name}"})
            results.append(ToolMessage(content=content, tool_call_id=tc_id))
        return {"messages": results}

    def should_continue(state) -> Literal["tools", "__end__"]:
        last_msg = state["messages"][-1]
        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
            return "tools"
        return "__end__"

    builder = StateGraph(MessagesState)
    builder.add_node("call_model", call_model)
    builder.add_node("tools", tools_node)
    builder.set_entry_point("call_model")
    builder.add_conditional_edges(
        "call_model", should_continue, {"tools": "tools", "__end__": END},
    )
    builder.add_edge("tools", "call_model")

    return builder.compile(checkpointer=MemorySaver())


# ============================================================
# Worker：按依赖层级执行 + 工具隔离
# ============================================================

class Task(TypedDict):
    id: str
    description: str
    depends_on: List[str]          # 依赖的任务 ID 列表


class OrchestratorState(TypedDict):
    query: str
    tasks: List[Task]              # 所有子任务（含依赖信息）
    completed_ids: List[str]       # 已完成的任务 ID
    results: Annotated[List[str], operator.add]  # worker 返回的结果
    final_answer: str


# ============================================================
# Supervisor：任务分解 + 依赖分析
# ============================================================

def supervisor(state: OrchestratorState):
    """用 LLM 分解任务并分析依赖关系"""
    llm = get_llm()
    prompt = f"""将以下用户请求分解为多个可执行的子任务，并分析它们之间的依赖关系。

输出格式（严格 JSON 数组，不要加额外文字）：
[
  {{"id": "1", "description": "子任务描述", "depends_on": []}},
  {{"id": "2", "description": "子任务描述", "depends_on": ["1"]}},
  ...
]

规则：
- depends_on 为空数组表示无前置依赖
- 如果任务 B 需要任务 A 的结果才能执行，B.depends_on 包含 A.id
- 每个独立的需求拆成一个子任务（比如"查时间"和"计算"是两个独立任务）
- 不需要合并多个子任务

请求: {state['query']}"""
    response = llm.invoke([HumanMessage(content=prompt)]).content or ""

    # 提取 JSON 数组（LLM 可能输出 markdown 代码块）
    json_match = re.search(r'\[.*?\]', response, re.DOTALL)
    if not json_match:
        return {"tasks": [{"id": "1", "description": state["query"], "depends_on": []}]}

    try:
        tasks = json.loads(json_match.group(0))
        # 验证每个 task 的字段
        validated = []
        for t in tasks:
            if isinstance(t, dict) and "id" in t and "description" in t:
                validated.append(Task(
                    id=str(t["id"]),
                    description=t["description"],
                    depends_on=[str(d) for d in t.get("depends_on", [])],
                ))
        if validated:
            print(f"\n[编排] 分解为 {len(validated)} 个子任务:")
            for t in validated:
                deps = f"（依赖 #{','.join(t['depends_on'])}）" if t['depends_on'] else "（无依赖）"
                print(f"  #{t['id']}: {t['description']} {deps}")
            return {"tasks": validated}
    except (json.JSONDecodeError, Exception):
        pass

    return {"tasks": [{"id": "1", "description": state["query"], "depends_on": []}]}


# ============================================================
# Worker：按依赖层级执行
# ============================================================

def worker_node(state: OrchestratorState):
    """按依赖层级执行子任务（同层可并行，层层等待）+ 工具隔离"""
    tasks = state.get("tasks", [])
    completed_ids = set(state.get("completed_ids", []))
    results = list(state.get("results", []))

    # 构建依赖图
    task_map = {t["id"]: t for t in tasks}

    def get_ready_tasks():
        """返回当前所有前置依赖已完成的任务"""
        ready = []
        for t in tasks:
            tid = t["id"]
            if tid in completed_ids:
                continue
            if all(d in completed_ids for d in t.get("depends_on", [])):
                ready.append(t)
        return ready

    def build_context(task: Task) -> str:
        """为有依赖的任务构建上下文（注入前置任务的结果）"""
        if not task.get("depends_on"):
            return ""
        context_parts = ["以下是已完成任务的结果，供你参考："]
        for r in results:
            for dep_id in task["depends_on"]:
                if f"[#{dep_id}]" in r:
                    context_parts.append(r)
        return "\n".join(context_parts) if len(context_parts) > 1 else ""

    # 逐层执行
    while True:
        ready = get_ready_tasks()
        if not ready:
            break

        level_results = {}
        if len(ready) == 1:
            # 单个任务直接执行
            t = ready[0]
            context = build_context(t)
            full_task = f"{t['description']}\n\n{context}" if context else t['description']
            answer = _run_single_worker(full_task)
            level_results[t["id"]] = f"[#{t['id']}] {t['description']}\n{answer}"
            print(f"  [完成] #{t['id']}: {t['description'][:50]}")
        else:
            # 多个任务并行执行
            def run_one(t):
                ctx = build_context(t)
                ft = f"{t['description']}\n\n{ctx}" if ctx else t['description']
                ans = _run_single_worker(ft)
                return t["id"], f"[#{t['id']}] {t['description']}\n{ans}"

            with ThreadPoolExecutor(max_workers=len(ready)) as ex:
                futures = {ex.submit(run_one, t): t for t in ready}
                for f in as_completed(futures):
                    tid, result = f.result()
                    level_results[tid] = result
                    print(f"  [完成] #{tid}: {futures[f]['description'][:50]}")

        # 更新完成状态
        for tid, result in level_results.items():
            completed_ids.add(tid)
            results.append(result)

    return {"results": results, "completed_ids": list(completed_ids)}


def _run_single_worker(task_description: str) -> str:
    """使用隔离的 Worker 执行单个子任务（只暴露相关工具）"""
    worker_app = _build_isolated_worker(task_description)
    result = worker_app.invoke({
        "messages": [
            SystemMessage(content="你是一个专注于子任务的 AI 助手。完成后输出 FINAL ANSWER。"),
            HumanMessage(content=task_description),
        ]
    }, {"recursion_limit": 12})
    for m in reversed(result["messages"]):
        if hasattr(m, "content") and m.content:
            return m.content.strip()
    return "（无输出）"


# ============================================================
# Join：合并结果
# ============================================================

def join(state: OrchestratorState):
    results = state.get("results", [])
    if not results:
        return {"final_answer": "没有可汇总的结果"}
    if len(results) == 1:
        return {"final_answer": results[0]}
    parts = [f"-- 结果{i} --\n{r}" for i, r in enumerate(results, 1)]
    return {"final_answer": "\n\n".join(parts)}


# ============================================================
# 构建图
# ============================================================

def build_orchestrator():
    builder = StateGraph(OrchestratorState)
    builder.add_node("supervisor", supervisor)
    builder.add_node("worker", worker_node)
    builder.add_node("join", join)
    builder.set_entry_point("supervisor")
    builder.add_conditional_edges(
        "supervisor",
        lambda s: "worker" if s.get("tasks") else "join",
    )
    builder.add_edge("worker", "join")
    builder.set_finish_point("join")
    return builder.compile()


def run(query: str) -> str:
    app = build_orchestrator()
    result = app.invoke({
        "query": query,
        "tasks": [],
        "completed_ids": [],
        "results": [],
        "final_answer": "",
    })
    return result.get("final_answer", "")
