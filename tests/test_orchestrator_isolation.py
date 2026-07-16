"""Concurrency and scheduling tests for the multi-agent orchestrator."""

from threading import Barrier, Lock

from react_agent.orchestrator import Orchestrator
from react_agent.planner import Task


def _tool_def(name: str) -> dict:
    return {"type": "function", "function": {"name": name}}


def test_parallel_workers_receive_isolated_tool_definitions():
    definitions = [
        _tool_def("get_current_time"),
        _tool_def("calculator"),
        _tool_def("execute_python"),
    ]
    original_names = [item["function"]["name"] for item in definitions]
    barrier = Barrier(2)
    lock = Lock()
    seen = {}

    def fake_loop(query, max_steps=None, tool_defs=None):
        del max_steps
        barrier.wait(timeout=2)
        names = {item["function"]["name"] for item in (tool_defs or [])}
        with lock:
            seen[query] = names
        return "ok"

    orchestrator = Orchestrator(lambda _: {}, fake_loop, definitions)
    tasks = [Task("1", "现在几点"), Task("2", "数学 1+1")]
    orchestrator.tasks = tasks

    orchestrator._execute_level_parallel(tasks, set())

    assert seen["现在几点"] == {"get_current_time"}
    assert seen["数学 1+1"] == {"calculator"}
    assert [item["function"]["name"] for item in definitions] == original_names


def test_parallel_false_uses_serial_path():
    calls = []

    def fake_loop(query, max_steps=None, tool_defs=None):
        del max_steps, tool_defs
        calls.append(query)
        return query

    orchestrator = Orchestrator(lambda _: {}, fake_loop)
    tasks = [Task("1", "first"), Task("2", "second")]
    orchestrator.tasks = tasks
    orchestrator._levels = [tasks]
    orchestrator.plan = lambda _: tasks

    def unexpected_parallel(*_args, **_kwargs):
        raise AssertionError("parallel executor must not run when parallel=False")

    orchestrator._execute_level_parallel = unexpected_parallel
    orchestrator.execute("ignored", parallel=False)

    assert calls == ["first", "second"]
