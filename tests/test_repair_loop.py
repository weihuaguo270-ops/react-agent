from react_agent.eval.repair_loop import RepairLoop, RepairLoopConfig


def plan():
    return {"replacements": [{"path": "src/app.py", "old": "x", "new": "y"}]}


def test_loop_repairs_after_public_failure_and_then_runs_hidden():
    calls = []
    outcomes = iter([{"passed": False}, {"passed": True}, {"passed": True}])

    def planner(context):
        calls.append(context["phase"])
        return plan()

    def executor(replacements, hidden):
        calls.append("hidden" if hidden else "public")
        return next(outcomes)

    result = RepairLoop(planner, executor, ("src/" ,), RepairLoopConfig(3)).run({"task_id": "t"})
    assert result["status"] == "succeeded"
    assert calls == ["planning", "public", "repair", "public", "hidden"]


def test_hidden_test_is_not_run_after_public_budget_exhaustion():
    calls = []

    def planner(_):
        return plan()

    def executor(_, hidden):
        calls.append(hidden)
        return {"passed": False}

    result = RepairLoop(planner, executor, ("src/" ,), RepairLoopConfig(2)).run({})
    assert result["status"] == "public_test_failed"
    assert calls == [False, False]


def test_invalid_plan_is_counted_and_bounded():
    result = RepairLoop(lambda _: {}, lambda *_: {"passed": True}, ("src/",), RepairLoopConfig(2)).run({})
    assert result["status"] == "public_test_failed"
    assert len(result["attempts"]) == 2


def test_observer_receives_audit_events_but_planner_never_sees_hidden_result():
    events = []
    planner_contexts = []

    class Observer:
        def emit(self, event, visibility):
            events.append((visibility, dict(event)))

    def planner(context):
        planner_contexts.append(dict(context))
        return plan()

    outcomes = iter([False, True, True])
    def executor(_, hidden):
        return {"passed": True, "secret": "hidden"} if hidden else {"passed": next(outcomes), "stderr": "retry"}

    result = RepairLoop(planner, executor, ("src/",), observer=Observer()).run({"task_id": "t"})
    assert result["status"] == "succeeded"
    assert any(v == "audit" and e["phase"] == "hidden_test" for v, e in events)
    assert all("secret" not in context.get("failure", {}) for context in planner_contexts)
