"""HTTP Evaluation Runner emits the shared Format B trajectory."""
from __future__ import annotations


def test_http_runner_trajectory_is_formal_format_b(monkeypatch):
    from react_agent.eval import http_execution
    from react_agent.harness.contracts import validate_trajectory

    monkeypatch.setattr(
        http_execution,
        "http_chat",
        lambda *_args, **_kwargs: (
            200,
            {
                "request_id": "req-1",
                "answer": "4",
                "agent_steps": [],
                "mode": "offline_react",
            },
        ),
    )
    runner = http_execution._http_agent_runner_factory("http://example.test")
    _stdout, trajectory, exit_code, _duration = runner("2+2")
    assert exit_code == 0
    assert trajectory["session_id"] == "req-1"
    assert trajectory["query"] == "2+2"
    assert trajectory["metadata"]["transport"] == "http"
    assert trajectory["metadata"]["execution_mode"] == "offline_react"
    assert trajectory["metadata"]["runtime_episode_id"].startswith("runtime-http-")
    assert validate_trajectory(trajectory) == []


def test_tool_boundary_canonicalizes_arguments():
    from react_agent.harness.tool_boundary import execute_registered_tool

    seen = {}

    def tool(**kwargs):
        seen.update(kwargs)
        return "ok"

    assert execute_registered_tool("demo", {"b": 2, "a": 1}, {"demo": tool}) == "ok"
    assert seen == {"a": 1, "b": 2}


def test_http_runner_preserves_server_execution_trajectory(monkeypatch):
    from react_agent.eval import http_execution

    monkeypatch.setattr(
        http_execution,
        "http_chat",
        lambda *_args, **_kwargs: (
            200,
            {
                "request_id": "req-2",
                "answer": "4",
                "mode": "workflow",
                "tools_called": ["calculator"],
                "trajectory": {
                    "session_id": "req-2",
                    "query": "2+2",
                    "final_answer": "4",
                    "steps": [
                        {
                            "step": 1,
                            "action": {"name": "calculator", "arguments": "{}"},
                            "observation": "4",
                        }
                    ],
                },
            },
        ),
    )
    runner = http_execution._http_agent_runner_factory("http://example.test")
    _stdout, trajectory, exit_code, _duration = runner("2+2")
    assert exit_code == 0
    assert trajectory["steps"][0]["action"]["name"] == "calculator"
    assert trajectory["metadata"]["execution_mode"] == "workflow"


def test_http_runner_records_server_error_with_stop_reason(monkeypatch):
    from react_agent.eval import http_execution
    from react_agent.harness.contracts import validate_trajectory

    monkeypatch.setattr(
        http_execution,
        "http_chat",
        lambda *_args, **_kwargs: (
            504,
            {"error": {"code": "timeout", "message": "upstream timed out"}, "request_id": "req-timeout"},
        ),
    )
    runner = http_execution._http_agent_runner_factory("http://example.test")
    stdout, trajectory, exit_code, _duration = runner("slow")
    assert exit_code == 1
    assert stdout == "upstream timed out"
    assert trajectory["metadata"]["stop_reason"] == "timeout"
    assert trajectory["metadata"]["error_code"] == "timeout"
    assert trajectory["metadata"]["runtime_episode_id"].startswith("runtime-http-")
    assert validate_trajectory(trajectory) == []


def test_http_runner_records_network_timeout(monkeypatch):
    from react_agent.eval import http_execution

    def timeout(*_args, **_kwargs):
        raise TimeoutError("socket deadline")

    monkeypatch.setattr(http_execution, "http_chat", timeout)
    runner = http_execution._http_agent_runner_factory("http://example.test")
    _stdout, trajectory, exit_code, duration = runner("slow")
    assert exit_code == 1
    assert duration >= 0
    assert trajectory["metadata"]["stop_reason"] == "timeout"
    assert trajectory["metadata"]["runtime_episode_id"].startswith("runtime-http-")


def test_http_runner_records_cancellation_reason(monkeypatch):
    from react_agent.eval import http_execution

    monkeypatch.setattr(
        http_execution,
        "http_chat",
        lambda *_args, **_kwargs: (
            499,
            {"error": {"code": "client_disconnected", "message": "cancelled"}, "request_id": "req-cancel"},
        ),
    )
    runner = http_execution._http_agent_runner_factory("http://example.test")
    _stdout, trajectory, exit_code, _duration = runner("cancel")
    assert exit_code == 1
    assert trajectory["metadata"]["stop_reason"] == "cancelled"
    assert trajectory["metadata"]["runtime_episode_id"].startswith("runtime-http-")


def test_http_runner_handles_non_object_error_payload(monkeypatch):
    from react_agent.eval import http_execution

    monkeypatch.setattr(
        http_execution,
        "http_chat",
        lambda *_args, **_kwargs: (500, ["upstream failure"]),
    )
    runner = http_execution._http_agent_runner_factory("http://example.test")
    stdout, trajectory, exit_code, _duration = runner("broken")
    assert exit_code == 1
    assert "upstream failure" in stdout
    assert trajectory["metadata"]["stop_reason"] == "tool_error"
    assert trajectory["metadata"]["runtime_episode_id"].startswith("runtime-http-")
