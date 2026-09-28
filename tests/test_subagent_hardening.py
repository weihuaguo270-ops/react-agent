"""Subagent 加固的契约测试：工具面声明、写冲突分层、深度/并发上限、fork 语义。

这些测试锁住 notes/plan-subagent-hardening.md 里三个已定稿决策：
1. 写冲突检测**默认开启**；
2. 未声明写集按**保守串行**处理；
3. fork 必须**如实标注**只看到摘要、且不继承工具与权限。
"""

from threading import Barrier, BrokenBarrierError, Lock

import pytest

from react_agent.orchestrator import (
    Orchestrator,
    SubagentDepthExceeded,
    current_delegation_depth,
    max_delegation_depth,
)
from react_agent.planner import Planner, Task
from react_agent.tool_scope import (
    ToolScope,
    UnknownToolScopeError,
    profiles_from_tags,
)
from react_agent.write_sets import (
    is_write_set_declared,
    normalize_write_path,
    write_sets_may_conflict,
)


def _tool_def(name: str) -> dict:
    return {"type": "function", "function": {"name": name}}


# ============================================================
# Phase 1：工具面声明化
# ============================================================

def test_scope_drops_unknown_names_instead_of_silently_widening():
    """声明里的未知工具名不得导致工具面被悄悄放大。"""
    defs = [_tool_def("calculator"), _tool_def("web_search")]
    scope = ToolScope(["calculator", "no_such_tool"])

    kept, unknown = scope.resolve(defs, strict=False)

    assert [d["function"]["name"] for d in kept] == ["calculator"]
    assert unknown == ["no_such_tool"]


def test_scope_strict_mode_raises_on_unknown_names():
    """strict 模式下未知工具名必须大声报错，而不是降级执行。"""
    defs = [_tool_def("calculator")]

    with pytest.raises(UnknownToolScopeError) as excinfo:
        ToolScope(["calculator", "typo_tool"]).resolve(defs, strict=True)

    assert "typo_tool" in str(excinfo.value)


def test_empty_scope_is_not_full_toolset():
    """空声明解析为空，不等于全量——回退必须由调用方显式决定。"""
    defs = [_tool_def("calculator"), _tool_def("web_search")]

    kept, unknown = ToolScope.empty().resolve(defs, strict=False)

    assert kept == []
    assert unknown == []
    assert not ToolScope.empty()


def test_profiles_expansion_is_explicit_not_keyword_guessed():
    """profile 展开只认已知标签，未知标签不会带出任何工具。"""
    assert profiles_from_tags(["calc"]) == frozenset({"calculator"})
    assert profiles_from_tags(["nope"]) == frozenset()


def test_worker_scope_distinguishes_registered_but_unexposed_tools(capsys):
    """已注册但不在本次可用集里的工具，应给出与"拼错"不同的诊断。

    这条路径才会去查注册表（装配 tools 包），所以只在确有必要时触发。
    """
    seen = {}

    def fake_loop(query, max_steps=None, tool_defs=None):
        seen["tools"] = {d["function"]["name"] for d in (tool_defs or [])}
        return "ok"

    defs = [_tool_def("calculator"), _tool_def("web_search")]
    orchestrator = Orchestrator(lambda _: {}, fake_loop, defs)
    task = Task("1", "数学 1+1")

    # get_time 已注册（Core 工具），但不在本次 all_defs 里
    orchestrator.run_worker(
        "数学 1+1", task_obj=task, declared_tools=["calculator", "get_time"]
    )

    output = capsys.readouterr().out
    assert seen["tools"] == {"calculator"}
    assert "已注册但本次未暴露" in output


def test_worker_scope_unknown_names_are_reported_not_swallowed(capsys):
    """Worker 侧收到未知工具名时必须打印告警（可诊断，不是静默）。"""
    seen = {}

    def fake_loop(query, max_steps=None, tool_defs=None):
        seen["tools"] = {d["function"]["name"] for d in (tool_defs or [])}
        return "ok"

    defs = [_tool_def("calculator"), _tool_def("web_search")]
    orchestrator = Orchestrator(lambda _: {}, fake_loop, defs)
    task = Task("1", "数学 1+1")

    orchestrator.run_worker("数学 1+1", task_obj=task, declared_tools=["calculator", "ghost_tool"])

    output = capsys.readouterr().out
    assert seen["tools"] == {"calculator"}
    assert "ghost_tool" in output
    assert "未知工具名" in output


# ============================================================
# Phase 2：写集冲突判定 + 分层（默认开启）
# ============================================================

def test_undeclared_write_sets_are_treated_as_conflicting():
    """未声明 / unknown 一律按可能冲突处理（保守串行）。"""
    assert write_sets_may_conflict(None, ["src/a.py"]) is True
    assert write_sets_may_conflict(["unknown"], ["src/a.py"]) is True
    assert write_sets_may_conflict([], []) is True
    assert is_write_set_declared(None) is False
    assert is_write_set_declared(["unknown"]) is False
    assert is_write_set_declared(["src/a.py"]) is True


def test_disjoint_write_sets_do_not_conflict_and_prefix_overlap_does():
    assert write_sets_may_conflict(["src/a.py"], ["src/b.py"]) is False
    # 目录与其下文件互为前缀 → 冲突
    assert write_sets_may_conflict(["src/api"], ["src/api/validate.py"]) is True
    # 大小写与分隔符归一化后仍判为冲突
    assert write_sets_may_conflict(["SRC\\Api\\"], ["src/api/v.py"]) is True
    assert normalize_write_path("SRC\\Api\\") == "src/api"


def test_schedule_with_write_conflicts_splits_overlapping_tasks():
    """同层写集相交的任务必须落到不同子层。"""
    tasks = [
        Task("1", "改前端", writes=["src/pages/login.tsx"]),
        Task("2", "改前端样式", writes=["src/pages/login.tsx"]),
        Task("3", "改后端", writes=["src/api/validate.py"]),
    ]

    segments = Planner.schedule_with_write_conflicts(tasks)

    # 1 与 2 相交 → 必须分开；3 与任一不相交 → 可与其中之一同段
    placement = {t.id: i for i, seg in enumerate(segments) for t in seg}
    assert placement["1"] != placement["2"]
    assert len(segments) == 2
    assert sorted(len(seg) for seg in segments) == [1, 2]


def test_schedule_with_write_conflicts_keeps_disjoint_tasks_parallel():
    """写集不相交时不得把并行能力一起关掉。"""
    tasks = [
        Task("1", "a", writes=["src/a.py"]),
        Task("2", "b", writes=["src/b.py"]),
    ]

    segments = Planner.schedule_with_write_conflicts(tasks)

    assert len(segments) == 1
    assert len(segments[0]) == 2


def test_schedule_keeps_dependency_ordering_with_write_sets():
    """写冲突分层不得破坏拓扑依赖顺序。"""
    tasks = [
        Task("1", "a", writes=["src/a.py"]),
        Task("2", "b", writes=["src/b.py"], depends_on=["1"]),
    ]

    segments = Planner.schedule_with_write_conflicts(tasks)

    placement = {t.id: i for i, seg in enumerate(segments) for t in seg}
    assert placement["1"] < placement["2"]


def _run_parallel_with_barrier(orchestrator, tasks, timeout=1.0):
    """用 Barrier 探测两个同层任务是否真的并发执行。

    返回 (并发发生?, 异常列表)。Barrier 被打破说明两者没有同时在跑。
    """
    barrier = Barrier(2)
    concurrent = {"value": False}
    lock = Lock()
    errors: list[Exception] = []

    def fake_loop(query, max_steps=None, tool_defs=None):
        del max_steps, tool_defs
        try:
            barrier.wait(timeout=timeout)
            with lock:
                concurrent["value"] = True
        except BrokenBarrierError as exc:  # 另一个任务没来 → 串行
            errors.append(exc)
        except Exception as exc:  # pragma: no cover - 防御
            errors.append(exc)
        return query

    orchestrator.react_loop = fake_loop
    orchestrator._execute_level_parallel(tasks, set())
    return concurrent["value"], errors


def _record_execution_segments(orchestrator, tasks, monkeypatch):
    """记录**实际**执行分组：每段一个 id 列表。

    不能只 spy ``_execute_level_parallel``：单任务段根本不走并行分支，
    会被漏掉。这里以 ``_execute_level_parallel`` 的调用作为「当前段」标记，
    用 ``run_worker`` 观测实际执行的任务，从而覆盖两条路径。
    """
    orchestrator.tasks = tasks
    orchestrator._levels = [tasks]
    orchestrator.plan = lambda _: tasks

    segments: list[list[str]] = []
    state = {"in_parallel": False}
    original_parallel = orchestrator._execute_level_parallel

    def parallel_spy(level, completed_ids):
        segments.append([t.id for t in level])
        state["in_parallel"] = True
        try:
            return original_parallel(level, completed_ids)
        finally:
            state["in_parallel"] = False

    real_worker = orchestrator.run_worker

    def worker_spy(task, *args, **kwargs):
        task_obj = kwargs.get("task_obj")
        # 并行段内的 run_worker 调用由 parallel_spy 统一记录，避免重复
        if task_obj is not None and not state["in_parallel"]:
            segments.append([task_obj.id])
        return real_worker(task, *args, **kwargs)

    monkeypatch.setattr(orchestrator, "_execute_level_parallel", parallel_spy)
    monkeypatch.setattr(orchestrator, "run_worker", worker_spy)
    orchestrator.execute("ignored", parallel=True)
    return segments


def test_overlapping_writes_never_share_a_parallel_segment(monkeypatch):
    """默认开启：写集相交的同层任务不会落在同一个执行段里。"""
    monkeypatch.delenv("REACT_AGENT_WRITE_CONFLICT_SERIALIZE", raising=False)
    orchestrator = Orchestrator(lambda _: {}, lambda q, **_: q)
    tasks = [
        Task("1", "alpha", writes=["src/shared.py"]),
        Task("2", "beta", writes=["src/shared.py"]),
        Task("3", "gamma", writes=["src/other.py"]),
    ]

    segments = _record_execution_segments(orchestrator, tasks, monkeypatch)

    placement = {tid: i for i, seg in enumerate(segments) for tid in seg}
    assert set(placement) == {"1", "2", "3"}, f"实际 {segments}"
    assert placement["1"] != placement["2"], f"相交写集必须分段，实际 {segments}"


def test_write_conflict_disjoint_writes_still_run_in_parallel(monkeypatch):
    """写集不相交时并行能力保持可用（防止把并行一起关掉）。"""
    monkeypatch.delenv("REACT_AGENT_WRITE_CONFLICT_SERIALIZE", raising=False)
    orchestrator = Orchestrator(lambda _: {}, lambda q, **_: q)
    tasks = [
        Task("1", "alpha", writes=["src/a.py"]),
        Task("2", "beta", writes=["src/b.py"]),
    ]

    concurrent, errors = _run_parallel_with_barrier(orchestrator, tasks)

    assert concurrent is True, f"应当并发执行，errors={errors}"


def test_undeclared_writes_are_serialized_by_default(monkeypatch):
    """未声明写集 → 保守串行：两个任务不会落进同一个执行段。"""
    monkeypatch.delenv("REACT_AGENT_WRITE_CONFLICT_SERIALIZE", raising=False)
    orchestrator = Orchestrator(lambda _: {}, lambda q, **_: q)
    tasks = [Task("1", "alpha"), Task("2", "beta")]

    segments = _record_execution_segments(orchestrator, tasks, monkeypatch)

    assert segments == [["1"], ["2"]], f"未声明写集必须串行，实际 {segments}"


def test_serialize_switch_off_restores_legacy_single_segment(monkeypatch):
    """关闭开关后回到历史行为：同层任务落回同一段（用于对照与回滚）。"""
    monkeypatch.setenv("REACT_AGENT_WRITE_CONFLICT_SERIALIZE", "0")
    orchestrator = Orchestrator(lambda _: {}, lambda q, **_: q)
    tasks = [
        Task("1", "alpha", writes=["src/shared.py"]),
        Task("2", "beta", writes=["src/shared.py"]),
    ]

    segments = _record_execution_segments(orchestrator, tasks, monkeypatch)

    assert segments == [["1", "2"]]


# ============================================================
# Phase 3：深度与并发上限
# ============================================================

def test_worker_concurrency_cap_is_honored(monkeypatch):
    """并发上限生效：给定 8 个同层任务 + cap=2，峰值并发不超过 2。"""
    monkeypatch.setenv("REACT_AGENT_SUBAGENT_MAX_CONCURRENCY", "2")
    lock = Lock()
    state = {"active": 0, "peak": 0}

    def fake_loop(query, max_steps=None, tool_defs=None):
        del max_steps, tool_defs
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        import time

        time.sleep(0.05)
        with lock:
            state["active"] -= 1
        return query

    orchestrator = Orchestrator(lambda _: {}, fake_loop)
    tasks = [Task(str(i), f"t{i}") for i in range(1, 9)]

    orchestrator._execute_level_parallel(tasks, set())

    assert state["peak"] <= 2


def test_delegation_depth_guard_rejects_when_exceeded(monkeypatch):
    """深度超限必须明确拒绝，且不产生副作用。"""
    monkeypatch.setenv("REACT_AGENT_SUBAGENT_MAX_DEPTH", "1")

    assert max_delegation_depth() == 1
    # 默认（无委派）深度为 0
    assert current_delegation_depth() == 0
    assert issubclass(SubagentDepthExceeded, RuntimeError)


# ============================================================
# Phase 4A：摘要式 fork 的诚实标注
# ============================================================

def test_fork_prompt_states_summary_is_not_full_history():
    orchestrator = Orchestrator(lambda _: {}, lambda q, **_: q)
    orchestrator.parent_summary = "父会话结论：认证模块需要补回归测试。"

    prompt = orchestrator._compose_worker_prompt("补测试", "", "fork")

    assert "摘要" in prompt
    assert "不是完整对话历史" in prompt
    assert "不继承父会话的工具与权限" in prompt
    assert "认证模块需要补回归测试" in prompt


def test_spawn_prompt_has_no_parent_context():
    orchestrator = Orchestrator(lambda _: {}, lambda q, **_: q)
    orchestrator.parent_summary = "不该出现在 spawn 里"

    prompt = orchestrator._compose_worker_prompt("独立任务", "", "spawn")

    assert prompt == "独立任务"
    assert "不该出现在 spawn 里" not in prompt


def test_multi_agent_chain_runs_the_real_orchestrator_path(monkeypatch, capsys):
    """回归：``multi_agent_chain`` 必须能在**不 stub Orchestrator** 的情况下跑通。

    此前该函数内联改写了 Orchestrator 的构造，却漏掉导入，真实 CLI 的
    ``--parallel`` 路径一调用就抛 NameError；而原先的用例把 Orchestrator
    patch 掉了，恰好绕过这个错误。这里让真实函数体执行，只把 Planner 的
    分解结果置空，从而不触达任何 LLM 调用。
    """
    from react_agent import react_loop as rl

    monkeypatch.delenv("REACT_AGENT_SUBAGENT_MAX_DEPTH", raising=False)
    monkeypatch.setattr(Planner, "plan", lambda self, query, llm_call=None: [])

    result = rl.multi_agent_chain("同时做两件事")

    assert result == ""
    output = capsys.readouterr().out
    assert "Planner 未返回任务" in output
    assert "NameError" not in output


def test_tool_scope_full_enumerates_definition_names():
    """回归：``ToolScope.full`` 曾调用一个不存在的辅助函数（NameError）。"""
    defs = [_tool_def("calculator"), _tool_def("web_search")]

    scope = ToolScope.full(defs)

    assert scope.names == {"calculator", "web_search"}
    assert scope.source == "full"
    # 结构异常的定义不应让枚举抛错
    assert ToolScope.full([{}, {"function": {}}, None]).names == set()


def test_fork_prompt_includes_upstream_context_when_present():
    orchestrator = Orchestrator(lambda _: {}, lambda q, **_: q)
    prompt = orchestrator._compose_worker_prompt("后续任务", "前置任务 #1 输出：x", "fork")

    assert "前置任务 #1 输出：x" in prompt
    assert "后续任务" in prompt


def test_planner_defaults_to_spawn_and_only_explicit_fork_switches():
    """只有显式 ``context: fork`` 才启用 fork；其余一律 spawn，不做推断。"""
    tasks = Planner._parse_tasks(
        "task_1: 独立任务\n"
        "task_2: 续接任务 | context: fork\n"
        "task_3: 可疑写法 | context: inherit\n"
    )

    assert [t.id for t in tasks] == ["1", "2", "3"]
    assert tasks[0].context_mode == "spawn"
    assert tasks[1].context_mode == "fork"
    assert tasks[2].context_mode == "spawn", "非 fork 的取值不得被猜成 fork"


def test_directive_parsing_preserves_writes_and_depends_on():
    """新指令段不能破坏既有 depends_on / writes 解析。"""
    tasks = Planner._parse_tasks(
        "task_1: 写测试 | writes: tests/a.py\n"
        "task_2: 续写 | depends_on: 1 | writes: src/a.py | context: fork\n"
    )

    assert tasks[0].writes == ["tests/a.py"]
    assert tasks[0].depends_on == []
    assert tasks[1].depends_on == ["1"]
    assert tasks[1].writes == ["src/a.py"]
    assert tasks[1].context_mode == "fork"


# ============================================================
# 解析器鲁棒性（三项修复）
# ============================================================

def test_depends_on_check_does_not_hijack_writes_values(capsys):
    """修复 1：含 ``depends_on`` 字样的**路径值**不得被当成依赖指令。

    旧实现用 ``"depends_on" in seg`` 做宽泛匹配，于是
    ``| writes: depends_on_helper.py`` 被解析成依赖 ``['writes: _helper.py']``
    ——一个永远无法满足的垃圾依赖，任务会被推到最后一层且日志显示"等待"。
    """
    tasks = Planner._parse_tasks(
        "task_1: 改前端 | writes: src/a.tsx\n"
        "task_2: 改后端 | writes: depends_on_helper.py\n"
    )

    assert len(tasks) == 2
    assert tasks[1].writes == ["depends_on_helper.py"]
    assert tasks[1].depends_on == [], f"不得产生垃圾依赖，实际 {tasks[1].depends_on}"

    # 两个任务写集不相交 → 应留在同一层（不再是"被推到最后一层"）
    levels = Planner.schedule(tasks)
    assert [[t.id for t in lv] for lv in levels] == [["1", "2"]]
    assert "无法识别" not in capsys.readouterr().out


def test_writes_value_that_is_not_a_path_degrades_to_unknown(capsys):
    """修复 2：不像路径的值必须整条降级为未声明，并告警（不接受假的安全声明）。"""
    tasks = Planner._parse_tasks(
        "task_1: 写前端 | writes: src/a.tsx (新建)\n"
        "task_2: 写后端 | writes: src/b.py; src/c.py\n"
    )

    output = capsys.readouterr().out
    assert tasks[0].writes is None, "带说明文字的路径值不得被当作有效声明"
    assert tasks[1].writes is None, "分号分隔不得被当作单一路径"
    assert "不像路径" in output

    # 降级后调度器按保守串行处理 — 这正是我们要的失效方向
    assert write_sets_may_conflict(tasks[0].writes, tasks[1].writes) is True


def test_quoted_write_paths_are_accepted():
    """带引号的路径（含空格）是合法形态，不应被降级。"""
    tasks = Planner._parse_tasks('task_1: x | writes: "src/my file.py", src/b.py\n')

    assert tasks[0].writes == ['"src/my file.py"', "src/b.py"]


def test_unknown_directive_is_reported_not_silently_dropped(capsys):
    """修复 3：不认识的指令（如拼错的 ``write:``）必须打印告警。"""
    tasks = Planner._parse_tasks(
        "task_1: 改前端 | write: src/a.tsx\n"
        "task_2: 改后端 | writes: src/b.py\n"
    )

    output = capsys.readouterr().out
    assert tasks[0].writes is None
    assert "忽略无法识别的指令" in output
    assert "write:" in output
    # 拼错导致未声明 → 保守串行，不会假装安全
    assert tasks[1].writes == ["src/b.py"]


def test_directive_name_variants_are_recognized(capsys):
    """指令名归一化：大小写、连字符、无冒号都应收敛到同一指令。"""
    tasks = Planner._parse_tasks(
        "task_1: a | Writes: src/a.py\n"
        "task_2: b | depends-on: 1 | writes: src/b.py\n"
        "task_3: c | DEPENDS ON: 1 | writes src/c.py\n"
    )

    output = capsys.readouterr().out
    assert tasks[0].writes == ["src/a.py"]
    assert tasks[1].depends_on == ["1"]
    assert tasks[2].depends_on == ["1"]
    assert tasks[2].writes == ["src/c.py"], "漏冒号的 writes 也应解析"
    assert "无法识别" not in output


def test_writes_unknown_marker_is_preserved_not_rejected(capsys):
    """``writes: unknown`` 是合法声明（明确的"不知道"），不能被当成垃圾值丢弃。"""
    tasks = Planner._parse_tasks("task_1: x | writes: unknown\n")

    assert tasks[0].writes == ["unknown"]
    assert "不像路径" not in capsys.readouterr().out


def test_legacy_format_without_directives_still_parses():
    """回归：只有描述、没有任何指令的旧格式必须继续可用。"""
    tasks = Planner._parse_tasks("task_1: 搜索天气\ntask_2: 对比 | depends_on: 1\n")

    assert [t.description for t in tasks] == ["搜索天气", "对比"]
    assert tasks[0].writes is None
    assert tasks[1].depends_on == ["1"]


def test_multi_agent_chain_refuses_when_depth_limit_exhausted(monkeypatch):
    """深度为 0 上限时，委派入口必须明确拒绝并给出可读原因。"""
    from react_agent import react_loop as rl

    monkeypatch.setenv("REACT_AGENT_SUBAGENT_MAX_DEPTH", "0")

    result = rl.multi_agent_chain("同时做两件事")

    assert "拒绝委派" in result
    assert "上限 0" in result


def test_multi_agent_chain_passes_parent_summary_to_orchestrator(monkeypatch):
    """parent_summary 必须真的传到 Orchestrator（否则 fork 任务拿不到摘要）。"""
    from react_agent import react_loop as rl
    from react_agent.orchestrator import Orchestrator as RealOrchestrator

    monkeypatch.delenv("REACT_AGENT_SUBAGENT_MAX_DEPTH", raising=False)
    captured = {}

    class SpyOrchestrator(RealOrchestrator):
        def execute(self, user_query, parallel=False):
            captured["summary"] = self.parent_summary
            captured["parallel"] = parallel
            return "stub"

    monkeypatch.setattr(rl, "Orchestrator", SpyOrchestrator, raising=False)
    # multi_agent_chain 内部懒加载 Orchestrator，需要打到 orchestrator 模块上
    import react_agent.orchestrator as orch_mod

    monkeypatch.setattr(orch_mod, "Orchestrator", SpyOrchestrator)

    result = rl.multi_agent_chain("同时做两件事", parallel=True, parent_summary="父级结论摘要")

    assert result == "stub"
    assert captured["summary"] == "父级结论摘要"
    assert captured["parallel"] is True
