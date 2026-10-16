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
