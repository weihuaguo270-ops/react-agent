"""Offline tests for the optional GitHub REST delivery backend."""
from __future__ import annotations

import json


class _Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


def test_github_backend_maps_ci_and_pr_calls(monkeypatch):
    from react_agent.server.github_backend import GitHubRESTBackend

    calls = []

    def fake_urlopen(req, timeout):
        calls.append((req.method, req.full_url, json.loads(req.data) if req.data else None, timeout))
        if req.method == "GET":
            return _Response({"check_runs": [
                {"name": "tests", "status": "completed", "conclusion": "success", "html_url": "u"},
            ]})
        if req.full_url.endswith("/pulls"):
            return _Response({"html_url": "https://github.com/example/repo/pull/1", "number": 1})
        return _Response({})

    monkeypatch.setattr("react_agent.server.github_backend.request.urlopen", fake_urlopen)
    backend = GitHubRESTBackend("token", api_base_url="https://api.test")
    status = backend.get_ci_status({"repository": "https://github.com/example/repo", "ref": "main"})
    assert status["status"] == "success"
    pr = backend.create_draft_pr({
        "repository": "https://github.com/example/repo",
        "base_branch": "main",
        "branch": "agent/task-1",
        "task_id": "task-1",
        "issue_url": "https://github.com/example/repo/issues/1",
        "plan_sha256": "abc",
    })
    assert pr["url"].endswith("/pull/1")
    triggered = backend.trigger_ci({
        "repository": "https://github.com/example/repo",
        "ref": "agent/task-1",
        "workflow": "tests.yml",
    })
    assert triggered["status"] == "queued"
    assert calls[0][0] == "GET"
    assert calls[1][0] == "POST"
    assert calls[2][1].endswith("/actions/workflows/tests.yml/dispatches")


def test_github_backend_rejects_non_github_repository():
    import pytest

    from react_agent.server.github_backend import GitHubRESTBackend

    backend = GitHubRESTBackend("token")
    with pytest.raises(ValueError, match="github.com"):
        backend.get_ci_status({"repository": "file:///tmp/repo", "ref": "main"})
