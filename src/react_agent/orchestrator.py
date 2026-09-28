"""
Orchestrator — 独立的多 Agent 协作模块

能力边界（诚实声明，勿夸大）：
- **有**：Worker 工具面按声明收窄；同层写冲突检测与串行化；委派深度与并发上限。
- **没有**：Worker 之间**没有工作区/文件系统隔离**。同层并行 Worker 共享同一个
  进程与同一个工作目录，并行修改同一文件仍会互相覆盖。当前的安全依赖是
  「写集声明 + 冲突分层」（见 planner.Task.writes），而不是隔离。真正的隔离
  （独立 worktree 或进程外执行）属于后续独立立项，见 docs/plan-subagent-hardening.md
  Phase 5。

本模块刻意不导入 react_loop / tools 等重模块（除函数内懒加载），以避免导入环。
"""
from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import ContextVar, copy_context
from typing import Iterable, Literal, Sequence

from react_agent.planner import Planner, Task
from react_agent.tool_scope import (
    PROFILE_HINTS,
    MAX_PROFILES as TOOL_PROFILES,
    ToolScope,
    def_names,
)
from react_agent.write_sets import (
    write_conflict_serialize_enabled,
)

__all__ = [
    "Orchestrator",
    "TOOL_PROFILES",
    "PROFILE_HINTS",
    "classify_tool_needs",
    "filter_tools",
    "SubagentDepthExceeded",
    "current_delegation_depth",
    "max_delegation_depth",
    "max_worker_concurrency",
    "write_conflict_serialize_enabled",
    "in_worker_context",
    "worker_memory_write_enabled",
]


# ============================================================
# 环境开关（统一 REACT_AGENT_* 前缀，与项目其余开关一致）
# ============================================================

def _env_flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


def max_delegation_depth() -> int:
    """委派深度上限；默认 1 = 允许直接子级、禁止更深嵌套（对齐 Codex max_depth）。"""
    return _env_int("REACT_AGENT_SUBAGENT_MAX_DEPTH", 1)


def max_worker_concurrency() -> int:
    """同层并行 Worker 数量上限；0 表示不限制（沿用历史行为，按层大小）。"""
    return _env_int("REACT_AGENT_SUBAGENT_MAX_CONCURRENCY", 4)


def worker_memory_write_enabled() -> bool:
    """Worker 是否允许回写长期记忆。**默认关闭**（子 Agent 不写全局记忆）。"""
    return _env_flag("REACT_AGENT_WORKER_MEMORY_WRITE", "0")


class SubagentDepthExceeded(RuntimeError):
    """委派深度超限。明确拒绝，不做静默截断。"""


# ============================================================
# 委派深度 / Worker 上下文（ContextVar，与项目既有 idiom 一致）
# ============================================================

_delegation_depth: ContextVar[int] = ContextVar("react_agent_delegation_depth", default=0)
_worker_context: ContextVar[bool] = ContextVar("react_agent_worker_context", default=False)


def current_delegation_depth() -> int:
    return _delegation_depth.get()


def in_worker_context() -> bool:
    """当前是否运行在 Worker 委派上下文内（供记忆边界等策略使用）。"""
    return _worker_context.get()


# ============================================================
# 工具面：声明式解析（Phase 1）
# ============================================================

# 兼容层：中文关键词 → profile 标签。
# 保留是为了不一次性打断既有调用方与测试，但**匹配失败时不再静默兜底**：
# 空标签会解析为空工具面，由调用方显式决定是否回退到全量。
_CLASSIFY_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("时间", "时区", "当前时间", "现在几点", "纽约", "伦敦"), "time"),
    (("文件", "目录", "文件夹", "大小", "写", "读", "创建"), "file"),
    (("搜索", "网页", "新闻", "查询"), "web"),
    (("计算", "数学", "等于"), "calc"),
    (("总结", "摘要", "概括"), "summary"),
    (("python", "代码", "脚本", "编写", "数据分析", "生成", "统计", "计算"), "code"),
)


def classify_tool_needs(task, call_llm=None) -> frozenset[str]:
    """按中文关键词推断需要的 profile 标签（**兼容层，已降级**）。

    历史行为：无命中时返回 ``{"web","calc"}`` 兜底。该兜底会在关键词漏词时
    静默给出错误工具集，因此现在返回空集合，由调用方决定是否回退——回退必须
    显式且可见。需要更强的判断请由调用方（或 Planner）显式声明工具面。
    """
    del call_llm  # 历史签名保留；本函数从未真正使用 LLM
    text = task.lower() if isinstance(task, str) else str(task).lower()
    tags: set[str] = set()
    for keywords, tag in _CLASSIFY_RULES:
        if any(word in text for word in keywords):
            tags.add(tag)
    return frozenset(tags)


def filter_tools(all_defs: Sequence[dict], needed_tags: Iterable[str]) -> list[dict]:
    """按 profile 标签取工具定义子集（**兼容层**）。

    注意与历史实现的差异：本函数只返回解析结果，未知工具名的处理交给
    :class:`ToolScope`；调用方若需要「未知即报错」请直接用 ToolScope。
    """
    scope = ToolScope.from_profiles(needed_tags)
    kept, unknown = scope.resolve(all_defs, strict=False)
    if unknown:  # pragma: no cover - profile 表来自本模块常量，正常不会触发
        print(f"[Scope] 未知工具被忽略: {', '.join(unknown)}")
    return kept


def _registry_names() -> set[str]:
    """当前注册表中的工具名（含 app 作用域视图）；失败时返回空集合。

    ⚠️ 调用它会装配整个 ``react_agent.tools`` 包（连带 app / workflow /
    experimental 工具与 RAG 语料），因此**只在确实需要区分"拼错"与"已注册但未
    暴露"时才调用**，不要放进常规路径。
    """
    try:
        from react_agent.tools import get_registry

        return set(get_registry())
    except Exception:
        return set()


def _def_names(all_defs: Iterable[dict]) -> set[str]:
    """从工具定义列表取名字；无成本、不触发任何导入。

    实现复用 ``tool_scope.def_names``，避免同一逻辑两处维护。
    """
    return def_names(all_defs)


def _resolve_worker_scope(
    task_text: str,
    all_defs: Sequence[dict],
    declared: Iterable[str] | None = None,
) -> ToolScope:
    """决定本次 Worker 的工具面。

    优先级：调用方显式声明 > 关键词推断 > 空（由调用方回退）。
    """
    if declared is not None:
        return ToolScope(declared, source="explicit")
    tags = classify_tool_needs(task_text)
    if tags:
        return ToolScope.from_profiles(tags)
    return ToolScope.empty()


# ============================================================
# 执行模式
# ============================================================

ExecutionMode = Literal["spawn", "fork"]
ContextMode = Literal["spawn", "fork"]


class Orchestrator:
    def __init__(self, call_llm_func, react_loop_func, tool_definitions=None):
        self.tasks: list[Task] = []
        self.results: list[str] = []
        self.call_llm = call_llm_func
        self.react_loop = react_loop_func
        self.all_tools = tool_definitions or []
        self.shared_data: dict[str, dict] = {}
        #: 可选的显式工具面声明：task_id → 工具名集合
        self.tool_scopes: dict[str, Iterable[str]] = {}
        #: 可选的显式写集声明：task_id → 路径列表（覆盖 Planner 的输出）
        self.write_sets: dict[str, list[str]] = {}
        #: 主会话的最终答案摘要，供 fork 模式的 Worker 使用（Phase 4A）
        self.parent_summary: str = ""

    # ----- 规划 -----

    def plan(self, user_query):
        planner = Planner()
        tasks = planner.plan(user_query, self.call_llm)
        if not tasks:
            print("[Orchestrator] Planner 未返回任务，使用默认 fallback")
            return []
        self.tasks = tasks
        self._levels = planner.schedule(tasks)
        print(f"\n[Orchestrator] 分解为 {len(tasks)} 个子任务，{len(self._levels)} 个执行层级:")
        for t in tasks:
            deps = f"（依赖 #{','.join(t.depends_on)}）" if t.depends_on else "（无依赖）"
            writes = f" writes={t.writes}" if t.writes else ""
            print(f"  #{t.id}: {t.description} {deps}{writes}")
        print()
        print(planner.describe_schedule(self._levels))
        return tasks

    # ----- 写集解析（Phase 2） -----

    def _write_set_for(self, task: Task) -> list[str] | None:
        """取任务写集：显式声明 > Planner 输出 > None（未知）。"""
        if task.id in self.write_sets:
            return list(self.write_sets[task.id])
        return task.writes

    # ----- Worker -----

    def run_worker(
        self,
        task,
        context="",
        task_obj: Task | None = None,
        context_mode: ContextMode = "spawn",
        declared_tools: Iterable[str] | None = None,
    ):
        print(f"\n{'='*50}")
        print(f"[Worker] {task}")
        task_with_context = self._compose_worker_prompt(task, context, context_mode)

        scope = _resolve_worker_scope(
            task_with_context if context else task,
            self.all_tools,
            declared=declared_tools,
        )
        # 先只与本次可用的工具定义求交（零成本）。只有当声明里出现了**不在可用集
        # 里**的名字时，才去查注册表来区分「拼错」与「已注册但未暴露」——后者需要
        # 装配整个 tools 包（含 RAG），不该为一次名字校验付这个代价。
        worker_tools, _ = scope.resolve(self.all_tools, strict=False)
        not_in_all_defs = sorted(
            n for n in scope.names if n not in _def_names(self.all_tools)
        )
        unknown: list[str] = []
        if not_in_all_defs:
            registry_names = _registry_names()
            unknown = [n for n in not_in_all_defs if n not in registry_names]
            for name in not_in_all_defs:
                if name in registry_names:
                    print(f"  [Scope] {name} 已注册但本次未暴露，Worker 无法调用")
        if unknown:
            print(f"  [Scope] 未知工具名（已忽略，未静默兜底）: {', '.join(unknown)}")
        if not scope and self.all_tools:
            # 空声明不自动等于全量；回退必须打印原因
            worker_tools = list(self.all_tools)
            scope = ToolScope.full(self.all_tools)
            print("  [Scope] 未匹配到任何声明 → 回退全量工具（原因：关键词与显式声明均为空）")
        print(f"  需要工具类型: {scope.source}")
        if self.all_tools:
            print(f"  暴露 {len(worker_tools)}/{len(self.all_tools)} 个工具")

        token = _worker_context.set(True)
        depth_token = _delegation_depth.set(current_delegation_depth() + 1)
        try:
            result = self.react_loop(task_with_context, tool_defs=worker_tools)
        finally:
            _delegation_depth.reset(depth_token)
            _worker_context.reset(token)

        if task_obj:
            self._capture_worker_outputs(task_obj, result, scope=scope)
        return result

    def _compose_worker_prompt(self, task: str, context: str, context_mode: ContextMode) -> str:
        """组装 Worker 的初始提示词。

        - ``spawn``：仅任务描述（+ 上游依赖结果）。Worker 是全新会话，看不到父级历史。
        - ``fork``（Phase 4A）：额外注入父会话**最终答案摘要**与上游结果，并且
          **如实说明这是摘要而非完整历史**。fork 不继承工具与权限（与 DSH 语义一致）。
        """
        parts: list[str] = []
        if context_mode == "fork":
            parts.append(
                "【上下文说明】你只看到父会话的答案摘要，不是完整对话历史，"
                "也不继承父会话的工具与权限。若摘要不足以完成任务，请明确说明缺口。"
            )
            if self.parent_summary.strip():
                parts.append(f"【父会话最终答案摘要】\n{self.parent_summary.strip()}")
        if context:
            parts.append(context)
        if parts:
            return f"{task}\n\n" + "\n\n".join(parts)
        return task

    def _capture_worker_outputs(self, task: Task, result, scope: ToolScope | None = None):
        try:
            # 必须用 context 局部读取：模块级 last_trajectory_steps 跨 worker 共享，
            # 并行时会把别的 worker 的工具输出算到本任务上，再经 _build_context
            # 作为【前置数据】注入下游依赖任务。
            from react_agent.react_loop import get_last_trajectory_steps

            outputs = []
            for step in get_last_trajectory_steps():
                obs = step.get("observation", "")
                act = step.get("action", {})
                name = act.get("name", "") if isinstance(act, dict) else ""
                if name and obs and obs not in ("None", ""):
                    outputs.append(f"[{name}] {obs[:2000]}")
                for multi_act in step.get("actions", []):
                    m_name = multi_act.get("name", "") if isinstance(multi_act, dict) else ""
                    m_obs = multi_act.get("observation", "")
                    if m_name and m_obs and m_obs not in ("None", ""):
                        outputs.append(f"[{m_name}] {m_obs[:2000]}")
            self.shared_data[task.id] = {
                "answer": result or "",
                "tool_outputs": outputs,
                "scope": scope.source if scope else "",
                "writes": self._write_set_for(task),
            }
        except Exception:
            self.shared_data[task.id] = {
                "answer": result or "",
                "tool_outputs": [],
                "scope": scope.source if scope else "",
                "writes": self._write_set_for(task),
            }

    def _build_context(self, task: Task, completed_ids: set[str]) -> str:
        if not task.depends_on:
            return ""
        parts = []
        for t in self.tasks:
            if t.id in task.depends_on:
                data = self.shared_data.get(t.id, {})
                tool_outputs = data.get("tool_outputs", [])
                numbers = None
                for out in tool_outputs:
                    nums = re.findall(r'\[([\d.,\s]+)\]', out)
                    if nums:
                        numbers = nums[0]
                        break
                if numbers:
                    parts.append(
                        f"【前置数据】\n"
                        f"上一步生成的数据如下，请直接在代码中用这个变量：\n"
                        f"data = {numbers}\n"
                    )
                if tool_outputs:
                    parts.append(f"前置任务 #{t.id} 输出：")
                    parts.extend(tool_outputs[:2])
        return "\n".join(parts)

    # ----- 汇总 -----

    def synthesize(self):
        if len(self.results) == 1:
            final = self.results[0]
        elif not self.results:
            final = "没有可汇总的结果"
        else:
            parts = [f"-- 结果{i} --\n{r}" for i, r in enumerate(self.results, 1)]
            final = "\n\n".join(parts)
        print(f"\n{'='*50}")
        print("[汇总结果]")
        print(final)
        return final

    # ----- 执行 -----

    def execute(self, user_query, parallel=False):
        self.plan(user_query)
        return self._run_planned(parallel=parallel)

    def _run_planned(self, parallel: bool = False) -> str:
        self.results = []
        completed_ids: set[str] = set()
        levels = getattr(self, "_levels", None)
        if not levels:
            print("[Orchestrator] 无任务可执行")
            return ""
        # 执行分层：在拓扑层级之上再按写集冲突切分（默认开启）。
        # 用 self.tasks 顺序保证 task 对象身份与 _levels 一致。
        if write_conflict_serialize_enabled():
            ordered = [t for level in levels for t in level]
            segments = Planner.schedule_with_write_conflicts(ordered)
            if len(segments) != len(levels):
                print(
                    f"  [写冲突] 拓扑 {len(levels)} 层 → 执行 {len(segments)} 段"
                    f"（写集可能相交的任务被拆开串行）"
                )
        else:
            segments = [list(level) for level in levels]
        for level_idx, segment in enumerate(segments, start=1):
            print(f"\n{'='*50}")
            print(f"[层级 {level_idx}/{len(segments)}] {len(segment)} 个任务")
            if parallel and len(segment) > 1:
                self._execute_level_parallel(segment, completed_ids)
                continue
            for t in segment:
                context = self._build_context(t, completed_ids)
                result = self.run_worker(
                    t.description,
                    context=context,
                    task_obj=t,
                    context_mode=getattr(t, "context_mode", "spawn"),
                )
                t.result = result
                self.results.append(f"[#{t.id}] {t.description}\n{result}")
                completed_ids.add(t.id)
        return self.synthesize()

    # ----- 并行执行 -----

    def _execute_level_parallel(
        self,
        level: list[Task],
        completed_ids: set[str],
    ):
        cap = max_worker_concurrency()
        workers = len(level) if cap == 0 else min(len(level), cap)
        if workers < len(level):
            print(f"  [并发] 上限 {cap}，本段 {len(level)} 个任务排队执行")

        def run_one(task: Task) -> tuple:
            context = self._build_context(task, completed_ids)
            result = self.run_worker(
                task.description,
                context=context,
                task_obj=task,
                context_mode=getattr(task, "context_mode", "spawn"),
            )
            return (task.id, result)

        # ThreadPoolExecutor 不传播 ContextVar：worker 线程拿到的是空 context，
        # 于是 react_loop 内部的 emit_event 会取到 default=None 并静默丢弃进度
        # 事件。这里为每个任务单独拷贝调用方的 context，让 SSE sink 等请求级
        # 上下文随任务进入 worker。
        # 注意必须「每任务一份」：同一个 Context 对象不能被并发 run()，共享一份
        # 会在多 worker 同时启动时抛 RuntimeError: cannot enter context。
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(copy_context().run, run_one, t): t for t in level}
            for f in as_completed(futures):
                t = futures[f]
                try:
                    tid, result = f.result()
                    t.result = result
                    self.results.append(f"[#{tid}] {t.description}\n{result}")
                    completed_ids.add(tid)
                    print(f"  [完成] #{tid}: {t.description[:50]}")
                except Exception as e:
                    print(f"  [失败] #{t.id}: {t.description[:50]}: {e}")


# ============================================================
# 写集冲突判定：实现见 react_agent/write_sets.py
# ============================================================
#
# 判定逻辑放在独立模块，因为 planner（冲突分层）与 orchestrator（执行分段）
# 都需要它，放在任一模块都会形成导入环。这里只保留一个诊断用的 JSON 兜底。

def _json_dumps_safe(payload) -> str:
    try:
        return json.dumps(payload, ensure_ascii=False)
    except Exception:  # pragma: no cover - 诊断兜底
        return "{}"
