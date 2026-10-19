from tests._load_eval_script import load_eval_script
from react_agent.harness.contracts import validate_trajectory

module = load_eval_script("run_github_business_tasks")


def test_github_business_tasks_preserve_source_and_exclude_pull_requests(monkeypatch):
    responses = iter([
        ({"full_name": "org/repo", "html_url": "https://github.com/org/repo"}, 10.0, "req-1"),
        ([{"number": 1, "title": "Issue", "labels": [], "html_url": "https://github.com/org/repo/issues/1"},
          {"number": 2, "title": "PR", "labels": [], "html_url": "x", "pull_request": {}}], 20.0, "req-2")])
    monkeypatch.setattr(module, "_get", lambda path: next(responses))
    report = module.run_github_tasks("org/repo")
    assert report["pass_rate"] == 1.0
    assert report["read_only"] is True
    assert report["cases"][1]["issue_sample"][0]["number"] == 1
    assert validate_trajectory(report["trajectory"]) == []
    assert report["fixture_manifest"]["environment"]["dataset_status"] == "live_snapshot"
    assert report["batch_id"]
    assert len(report["evaluation_episodes"]) == 2
    assert all(episode["batch_id"] == report["batch_id"] for episode in report["evaluation_episodes"])
    assert all(episode["fixture_manifest"] == report["fixture_manifest"] for episode in report["evaluation_episodes"])
    assert all(episode["artifacts"][0]["sha256"] for episode in report["evaluation_episodes"])


def test_github_token_falls_back_to_gh_without_printing_secret(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(module.shutil, "which", lambda name: "gh")
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs:
                        module.subprocess.CompletedProcess(args[0], 0, "secret-token\n", ""))
    assert module._github_token() == "secret-token"

