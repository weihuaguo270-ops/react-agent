from __future__ import annotations

from react_agent.harness import (
    HttpRunnerAdapter,
    ReactLoopAdapter,
    RuntimeEpisode,
    StopReason,
    WorkflowAdapter,
    assert_valid,
)


def test_react_loop_adapter_emits_runtime_episode_and_format_b():
    adapter = ReactLoopAdapter(loop=lambda query, **kwargs: "answer")
    episode = adapter.run("hello", max_steps=2, evaluation_episode_id="eval-1")

    assert isinstance(episode, RuntimeEpisode)
    assert episode.execution_mode == "react"
    assert episode.status == "completed"
    assert episode.stop_reason == StopReason.COMPLETED
    assert episode.evaluation_episode_id == "eval-1"
    assert episode.trajectory["metadata"]["runtime_episode_id"] == episode.runtime_episode_id
    assert_valid(episode.trajectory)
    restored = RuntimeEpisode.from_mapping(episode.to_dict())
    assert restored.runtime_episode_id == episode.runtime_episode_id
    assert restored.trajectory == episode.trajectory


def test_runtime_adapters_emit_completed_episodes_to_injected_observer():
    exported = []

    class Observer:
        def emit(self, episode):
            exported.append(episode)

    observer = Observer()
    react = ReactLoopAdapter(loop=lambda query, **kwargs: "answer", observability=observer)
    react_episode = react.run("hello")

    payload = {
        "mode": "react",
        "answer": "answer",
        "trajectory": {
            "session_id": "http-obs",
            "query": "hello",
            "final_answer": "answer",
            "steps": [{"step": 1, "observation": "done"}],
        },
    }
    _, http_episode = HttpRunnerAdapter(observability=observer).adapt_response(
        payload, request_id="http-obs"
    )

    assert exported == [react_episode, http_episode]


def test_http_chat_collects_llm_usage_into_runtime_episode(monkeypatch):
    import react_agent.server.chat_router as chat_router
    from react_agent.llm import _record_usage

    monkeypatch.setenv("REACT_AGENT_OBSERVABILITY_EXPORTER", "none")

    def fake_chat(_body, _request_id):
        _record_usage(
            {"prompt_tokens": 100, "completion_tokens": 20},
            pricing={
                "input_usd_per_million_tokens": 0.15,
                "output_usd_per_million_tokens": 0.60,
            },
        )
        return 200, {
            "mode": "react",
            "answer": "ok",
            "trajectory": {
                "session_id": "usage-http",
                "query": "q",
                "final_answer": "ok",
                "steps": [{"step": 1, "observation": "done"}],
            },
        }

    monkeypatch.setattr(chat_router, "_handle_chat", fake_chat)
    status, payload = chat_router.handle_chat({}, "usage-http")

    assert status == 200
    assert payload["runtime_episode"]["metrics"]["tokens"] == 120
    assert payload["runtime_episode"]["metrics"]["estimated_cost"] == 0.000027


def test_react_loop_adapter_collects_retry_and_trajectory_token_metrics():
    from react_agent.harness import RetryPolicy

    attempts = []

    def loop(query, **kwargs):
        def operation():
            attempts.append(1)
            if len(attempts) == 1:
                raise TimeoutError("transient")
            return "ok"

        RetryPolicy(max_attempts=2, base_delay=0, jitter_ratio=0).run(
            operation, sleep_fn=lambda _delay: None
        )
        return {
            "answer": "ok",
            "agent_steps": [{"step": 1, "observation": "ok", "tokens_estimated": 7}],
        }

    episode = ReactLoopAdapter(loop=loop).run("q")

    assert episode.metrics["retry_count"] == 1
    assert episode.metrics["tokens"] == 7


def test_workflow_adapter_maps_refusal_and_keeps_workflow_mode():
    class Result:
        run_id = "wf-test"
        ok = False
        refused = True
        answer = "denied"

        def to_trajectory(self):
            return {
                "session_id": "wf-test",
                "query": "q",
                "final_answer": "denied",
                "steps": [{"step": 1, "observation": "denied"}],
                "metadata": {"stop_reason": "policy_denied"},
            }

    episode = WorkflowAdapter(runner=lambda *args, **kwargs: Result()).run("wf", {"query": "q"})
    assert episode.execution_mode == "workflow"
    assert episode.status == "refused"
    assert episode.stop_reason == StopReason.POLICY_DENIED
    assert_valid(episode.trajectory)


def test_workflow_adapter_maps_timeout_to_runtime_episode():
    episode = WorkflowAdapter(
        runner=lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("deadline"))
    ).run("wf", {"query": "q"})

    assert episode.status == "timeout"
    assert episode.stop_reason == StopReason.TIMEOUT
    assert episode.metrics["cancelled"] == 0
    assert episode.trajectory["metadata"]["stop_reason"] == "timeout"
    assert_valid(episode.trajectory)


def test_workflow_adapter_maps_cancellation_to_runtime_episode():
    from react_agent.llm import LLMCancelled

    episode = WorkflowAdapter(
        runner=lambda *args, **kwargs: (_ for _ in ()).throw(LLMCancelled("client disconnected"))
    ).run("wf", {"query": "q"})

    assert episode.status == "cancelled"
    assert episode.stop_reason == StopReason.CANCELLED
    assert episode.metrics["cancelled"] == 1
    assert episode.trajectory["metadata"]["stop_reason"] == "cancelled"
    assert_valid(episode.trajectory)


def test_http_runner_adapter_preserves_source_execution_mode():
    payload = {
        "mode": "workflow",
        "run_id": "wf-1",
        "answer": "ok",
        "trajectory": {
            "session_id": "wf-1",
            "query": "q",
            "final_answer": "ok",
            "steps": [{"step": 1, "observation": "ok"}],
            "metadata": {"execution_mode": "workflow"},
        },
    }
    adapted, episode = HttpRunnerAdapter().adapt_response(payload, request_id="req-1")

    assert adapted["execution_mode"] == "workflow"
    assert adapted["runtime_episode_id"] == episode.runtime_episode_id
    assert adapted["runtime_episode"]["transport"] == "http"
    assert adapted["trajectory"]["metadata"]["runtime_episode_id"] == episode.runtime_episode_id
    assert_valid(adapted["trajectory"])


def test_http_runner_adapter_preserves_evaluation_episode_link():
    adapted, episode = HttpRunnerAdapter().adapt_response(
        {
            "mode": "react",
            "evaluation_episode_id": "eval-http-1",
            "answer": "ok",
            "trajectory": {
                "session_id": "req-eval",
                "query": "q",
                "final_answer": "ok",
                "steps": [{"step": 1, "observation": "ok"}],
            },
        },
        request_id="req-eval",
    )

    assert episode.evaluation_episode_id == "eval-http-1"
    assert adapted["runtime_episode"]["evaluation_episode_id"] == "eval-http-1"


def test_http_runner_adapter_maps_policy_denied_to_refused():
    payload = {
        "mode": "workflow",
        "refused": True,
        "trajectory": {
            "session_id": "wf-denied",
            "query": "q",
            "final_answer": "denied",
            "steps": [{"step": 1, "observation": "denied"}],
            "metadata": {"execution_mode": "workflow", "stop_reason": "policy_denied"},
        },
    }
    adapted, episode = HttpRunnerAdapter().adapt_response(
        payload, request_id="req-denied", status_code=400
    )

    assert episode.status == "refused"
    assert episode.stop_reason == StopReason.POLICY_DENIED
    assert adapted["runtime_episode"]["status"] == "refused"


def test_react_workflow_and_http_adapters_share_terminal_reason_matrix():
    from types import SimpleNamespace

    from react_agent.harness.runtime.structured_output import StructuredOutputContract
    from react_agent.llm import LLMCancelled

    contract = StructuredOutputContract(
        "answer", {"type": "object", "required": ["answer"], "properties": {"answer": {"type": "string"}}}
    )
    cases = {
        "timeout": (TimeoutError("deadline"), 504),
        "cancelled": (LLMCancelled("client left"), 499),
        "policy_denied": (PermissionError("approval required"), 403),
        "tool_error": (RuntimeError("tool failed"), 500),
    }
    observed = {"react": {}, "workflow": {}, "http": {}}

    for expected, (error, status_code) in cases.items():
        react = ReactLoopAdapter(loop=lambda *_a, _error=error, **_k: (_ for _ in ()).throw(_error)).run("q")
        observed["react"][expected] = react.stop_reason.value

        workflow = WorkflowAdapter(
            runner=lambda *_a, _error=error, **_k: (_ for _ in ()).throw(_error)
        ).run("wf", {"query": "q"})
        observed["workflow"][expected] = workflow.stop_reason.value

        _, http = HttpRunnerAdapter().adapt_response(
            {"mode": "react", "error": {"message": str(error)},
             "trajectory": {"session_id": "http-terminal", "query": "q", "final_answer": "",
                            "steps": [{"step": 1, "observation": str(error)}],
                            "metadata": {"stop_reason": expected}}},
            request_id=f"http-{expected}", status_code=status_code,
        )
        observed["http"][expected] = http.stop_reason.value

    react_invalid = ReactLoopAdapter(loop=lambda *_a, **_k: {"answer": "not-json"}).run(
        "q", structured_output_contract=contract
    )
    observed["react"]["parse_error"] = react_invalid.stop_reason.value

    class InvalidWorkflowResult:
        run_id = "wf-invalid"
        ok = True
        refused = False
        answer = "not-json"

        def to_trajectory(self):
            return {"session_id": self.run_id, "query": "q", "final_answer": self.answer,
                    "steps": [{"step": 1, "observation": self.answer}]}

    workflow_invalid = WorkflowAdapter(runner=lambda *_a, **_k: InvalidWorkflowResult()).run(
        "wf", {"query": "q"}, structured_output_contract=contract
    )
    observed["workflow"]["parse_error"] = workflow_invalid.stop_reason.value

    _, http_invalid = HttpRunnerAdapter().adapt_response(
        {"mode": "react", "answer": "not-json",
         "trajectory": {"session_id": "http-invalid", "query": "q", "final_answer": "not-json",
                        "steps": [{"step": 1, "observation": "not-json"}]}},
        request_id="http-parse-error", structured_output_contract=contract,
    )
    observed["http"]["parse_error"] = http_invalid.stop_reason.value

    expected_matrix = {
        "timeout": "timeout", "cancelled": "cancelled", "policy_denied": "policy_denied",
        "tool_error": "tool_error", "parse_error": "parse_error",
    }
    assert observed == {path: expected_matrix for path in ("react", "workflow", "http")}
