from examples.eval import run_github_portfolio_dataset as module


def _responses(repository):
    base = f"https://github.com/{repository}"
    return iter([
        ({"full_name": repository, "html_url": base, "open_issues_count": 4,
          "stargazers_count": 10, "forks_count": 2, "updated_at": "2026-08-13T00:00:00Z",
          "language": "Python", "topics": ["agent"], "archived": False, "disabled": False,
          "license": {"spdx_id": "MIT"}}, 10.0, "req-repo"),
    ])


def test_dataset_has_50_tasks_cluster_splits_and_fingerprint(monkeypatch):
    responses = {repo: _responses(repo) for repo in module.REPOSITORIES}

    def fake_get(path):
        parts = path.split("/repos/", 1)[1].split("/")
        return next(responses["/".join(parts[:2])])

    monkeypatch.setattr(module, "_get", fake_get)
    report = module.run_dataset(preflight=False)
    assert report["dataset"]["task_count"] == 50
    assert report["dataset"]["split_counts"] == {"dev": 15, "golden": 20, "held_out": 15}
    assert len(report["dataset"]["fingerprint_sha256"]) == 64
    assert report["completion_gate"]["passed"] is True
    assert report["metrics"]["human_handoff_rate"] == 0.0
    assert report["cases"][2]["answer"]["stars"] == 10


def test_traceability_gate_rejects_missing_request_id(monkeypatch):
    responses = _responses("org/repo")

    def fake_get(path):
        payload, latency, _ = next(responses)
        return payload, latency, None

    monkeypatch.setattr(module, "_get", fake_get)
    report = module.run_dataset(("org/repo",), preflight=False)
    assert report["completion_gate"]["source_traceability"] is False
    assert report["completion_gate"]["passed"] is False


def test_cache_allows_resume_without_network(monkeypatch, tmp_path):
    responses = _responses("org/repo")
    monkeypatch.setattr(module, "_get", lambda path: next(responses))
    first = module.run_dataset(("org/repo",), cache_dir=tmp_path, preflight=False)
    monkeypatch.setattr(module, "_get", lambda path: (_ for _ in ()).throw(AssertionError("network called")))
    second = module.run_dataset(("org/repo",), cache_dir=tmp_path, preflight=False)
    assert first["cases"] == second["cases"]


def test_preflight_blocks_before_partial_collection(monkeypatch):
    monkeypatch.setattr(module, "_preflight", lambda required: {
        "authenticated": False, "limit": 60, "remaining": 2, "reset": 1,
        "required_requests": required, "passed": False, "latency_ms": 1, "request_id": "req",
    })
    monkeypatch.setattr(module, "_get", lambda path: (_ for _ in ()).throw(AssertionError("collection started")))
    report = module.run_dataset(("org/repo",))
    assert report["dataset"]["task_count"] == 0
    assert report["failure_slices"]["repository_errors"][0]["error_type"] == "RateLimitBudget"
