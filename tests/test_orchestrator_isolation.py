"""Concurrency and scheduling tests for the multi-agent orchestrator."""

from threading import Barrier, Lock

from react_agent.harness import current_trajectory, finish_trajectory, start_trajectory
from react_agent.orchestrator import Orchestrator
from react_agent.planner import Task
from react_agent.server.streaming import emit_event, reset_event_sink, set_event_sink


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


def test_parallel_workers_inherit_contextvar_event_sink():
    """Progress events must survive the hop into ThreadPoolExecutor workers.

    ``ThreadPoolExecutor`` does not copy the caller's context, so without an
    explicit per-task ``copy_context()`` the worker-side ``emit_event`` sees
    ``default=None`` and silently drops every event.  The barrier forces both
    workers to be inside the pool simultaneously, which also guards against
    "optimising" this to one shared context object (that raises
    ``RuntimeError: cannot enter context``).
    """
    barrier = Barrier(2)
    lock = Lock()
    entered = []

    def fake_loop(query, max_steps=None, tool_defs=None):
        del max_steps, tool_defs
        barrier.wait(timeout=5)
        emit_event("tool_call", {"worker": query})
        with lock:
            entered.append(query)
        return query

    orchestrator = Orchestrator(lambda _: {}, fake_loop)
    tasks = [Task("1", "alpha"), Task("2", "beta")]

    received = []
    token = set_event_sink(lambda event, data: received.append((event, data.get("worker"))))
    try:
        orchestrator._execute_level_parallel(tasks, set())
    finally:
        reset_event_sink(token)

    assert sorted(entered) == ["alpha", "beta"]
    assert sorted(worker for _, worker in received) == ["alpha", "beta"]


def test_parallel_workers_keep_isolated_trajectories(monkeypatch):
    """Each parallel worker must own its trajectory.

    With a module-level global the second ``start_trajectory`` clobbers the
    first, so a worker records its steps into another worker's trajectory --
    and once either side calls ``finish_trajectory`` the other silently stops
    recording.  The barrier holds both workers inside the racy window.
    """
    from react_agent.harness import recorder

    monkeypatch.setattr(recorder.Trajectory, "save", lambda self: None)
    barrier = Barrier(2)
    lock = Lock()
    observed = {}

    def fake_loop(query, max_steps=None, tool_defs=None):
        del max_steps, tool_defs
        start_trajectory(query, "fake-model")
        barrier.wait(timeout=5)
        with lock:
            observed[query] = getattr(current_trajectory(), "query", None)
        finish_trajectory(query)
        return query

    orchestrator = Orchestrator(lambda _: {}, fake_loop)
    tasks = [Task("1", "alpha"), Task("2", "beta")]

    orchestrator._execute_level_parallel(tasks, set())

    assert observed == {"alpha": "alpha", "beta": "beta"}


def test_capture_worker_outputs_is_not_cross_attributed(monkeypatch):
    """Worker A must never pick up worker B's tool outputs.

    Captured outputs feed ``_build_context`` as 【前置数据】 for downstream
    tasks, so cross-attribution silently corrupts the final answer rather than
    only the observability trail.
    """
    from react_agent.harness import recorder
    from react_agent.react_loop import _finish_with_save

    monkeypatch.setattr(recorder.Trajectory, "save", lambda self: None)
    barrier = Barrier(2)

    def fake_loop(query, max_steps=None, tool_defs=None):
        del max_steps, tool_defs
        traj = start_trajectory(query, "fake-model")
        traj.add_tool_call(1, f"tool_{query}", "{}", f"obs_{query}")
        barrier.wait(timeout=5)
        _finish_with_save(query)
        return query

    orchestrator = Orchestrator(lambda _: {}, fake_loop)
    tasks = [Task("1", "alpha"), Task("2", "beta")]

    orchestrator._execute_level_parallel(tasks, set())

    alpha = orchestrator.shared_data["1"]["tool_outputs"]
    beta = orchestrator.shared_data["2"]["tool_outputs"]
    assert alpha and all("tool_alpha" in item for item in alpha)
    assert beta and all("tool_beta" in item for item in beta)
