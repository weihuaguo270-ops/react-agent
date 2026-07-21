"""LangGraph path → Harness Format B thin contract.

Does not require step-by-step behavioral parity with Core ``react_loop``.

Covers:
1. LangGraph recorder output passes ``validate_trajectory``
2. ``source == \"graph\"`` and ``schema_version``
3. Framework demo compiles when langgraph is installed
"""
from __future__ import annotations

import importlib.util
import os
import sys

import pytest

from react_agent.harness.schema import validate_trajectory


def _load_graph_recorder():
    """按文件路径加载 experiments 下的 recorder（不在 src 包内）。"""
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    path = os.path.join(
        root, "experiments", "langgraph", "graph", "harness", "recorder.py"
    )
    spec = importlib.util.spec_from_file_location(
        "langgraph_traj_recorder", path
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod.TrajectoryRecorder


def test_langgraph_recorder_emits_format_b():
    Recorder = _load_graph_recorder()
    rec = Recorder(
        query="demo contract query",
        model="mock-graph",
        system_prompt="LangGraph twin",
    )
    rec.record_thought(step=1, thought="need calculator", tokens=12)
    rec.record_action(
        step=1,
        action_name="calculator",
        action_args='{"expression":"1+1"}',
        observation="2",
        duration_seconds=0.01,
        tokens=4,
    )
    rec.set_final_answer("2")
    data = rec.to_dict()

    assert data.get("source") == "graph"
    assert data.get("schema_version") == "1"
    issues = validate_trajectory(data)
    assert issues == [], f"Format B issues: {issues}"


def test_langgraph_framework_demo_compiles():
    pytest.importorskip("langgraph")
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    demo_path = os.path.join(
        root, "experiments", "langgraph", "demo_checkpoint_hitl.py"
    )
    spec = importlib.util.spec_from_file_location("lg_demo_ckpt", demo_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)

    app = mod._build_app(auto_approve=True)
    config = {"configurable": {"thread_id": "contract-test"}}
    out = app.invoke(
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
    assert out.get("pending_tool") == "execute_python"
    assert out.get("observation") in ("2", "blocked:execute_python")
    # auto_approve=True → should act
    assert out.get("observation") == "2"
    snap = app.get_state(config)
    assert snap.values.get("turn") == 1
