"""Pytest-owned checks migrated from the standalone ``test_all.py`` script."""

import re
import tempfile
from pathlib import Path


def test_cot_strategy_injection_and_parser_smoke():
    from react_agent.cot import COT, COT_TOOL_DEFINITION, CoTStrategy, extract_reasoning

    assert COT.select("计算5只鸡和3只兔子一共多少条腿") == CoTStrategy.FEW_SHOT_MATH
    assert COT.select("如果下雨就不去") == CoTStrategy.FEW_SHOT_REASONING
    assert COT.select("搜索今天天气") == CoTStrategy.ZERO_SHOT
    injected = COT.inject("base", query="计算1+1")
    assert "base" in injected and "THOUGHT" in injected
    assert "switch_cot_strategy" in str(COT_TOOL_DEFINITION)
    thoughts, answer = extract_reasoning("THOUGHT: 第一步\nFINAL ANSWER: 答案")
    assert thoughts == ["第一步"]
    assert answer == "答案"


def test_tot_tree_and_parsing_smoke():
    from react_agent.tot import SearchStrategy, ToT, ToTNode

    root = ToTNode("")
    first = ToTNode("第一步", root)
    second = ToTNode("第二步", root)
    first.score = 8.0
    second.score = 3.0
    assert root.best_child() is first
    assert first.chain() == ["第一步"]
    assert len(root.children) == 2

    tree = ToT(beam_width=2, branch_factor=2, max_depth=2)
    assert tree._parse_candidates("步骤1: A\n---\n步骤2: B") == ["A", "B"]
    assert tree._parse_candidates("直接回答没按格式")
    assert [tree._parse_score(value) for value in ("8", "7/10", "评分: 6", "好的")] == [8.0, 7.0, 6.0, 5.0]
    assert SearchStrategy.BFS.value == "bfs"
    assert SearchStrategy.DFS.value == "dfs"


def test_planner_parse_schedule_and_readiness_smoke():
    from react_agent.planner import Planner, Task

    tasks = Planner._parse_tasks(
        "task_1: 搜索今天\ntask_2: 搜索明天\ntask_3: 对比 | depends_on: 1, 2"
    )
    assert len(tasks) == 3
    assert tasks[0].description == "搜索今天"
    assert tasks[2].depends_on == ["1", "2"]
    levels = Planner.schedule(tasks)
    assert [len(level) for level in levels] == [2, 1]

    independent = Task("1", "A")
    dependent = Task("2", "B", depends_on=["1"])
    assert independent.ready(set())
    assert not dependent.ready(set())
    assert dependent.ready({"1"})


def test_role_manager_selection_and_mutation_smoke():
    from react_agent.prompts import ROLE_MANAGER, Role

    original = ROLE_MANAGER.current_role_name()
    try:
        assert ROLE_MANAGER.select("帮我审查代码") == Role.CODE_REVIEWER
        assert ROLE_MANAGER.select("什么是装饰器") == Role.TUTOR
        assert ROLE_MANAGER.select("对比A和B") == Role.DEBATER
        assert ROLE_MANAGER.select("今天天气") == Role.RESEARCH_ASSISTANT
        enhanced = ROLE_MANAGER.inject("base prompt", query="帮我审查代码")
        assert "审查" in enhanced and "base prompt" in enhanced
        assert "tutor" in ROLE_MANAGER.set_role("tutor")
        assert ROLE_MANAGER.current_role_name() == "tutor"
        assert "未知" in ROLE_MANAGER.set_role("unknown")
        assert len(ROLE_MANAGER.list_roles()) == 5
        assert "tutor" in ROLE_MANAGER.list_roles()
    finally:
        ROLE_MANAGER.set_role(original)


def test_memory_keyword_fallback_smoke(monkeypatch):
    from react_agent import memory as memory_module
    from react_agent.memory import Memory

    monkeypatch.setattr(memory_module, "_HAS_VECTOR", False)
    with tempfile.TemporaryDirectory(prefix="react-agent-memory-smoke-") as directory:
        memory = Memory(save_path=str(Path(directory) / "memory.json"))
        assert memory.query("test") == []
        memory.add("小明是学生")
        assert memory.query("小明")
        assert memory.remove("小明")
        assert memory.query("小明") == []


def test_orchestrator_template_smoke():
    from react_agent.orchestrator import Planner

    planner = Planner()
    query = "搜索今天北京和上海的天气，对比温差"
    tasks = None
    for pattern, builder in planner._TEMPLATES:
        match = re.search(pattern, query)
        if match:
            tasks = builder(match)
            if tasks:
                break

    assert tasks is not None
    assert len(tasks) == 3
    assert "今天" in tasks[0].description
    assert tasks[2].depends_on == ["1", "2"]
