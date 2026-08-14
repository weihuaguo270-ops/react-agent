from examples.eval import run_github_business_tasks as module


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


def test_github_token_falls_back_to_gh_without_printing_secret(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(module.shutil, "which", lambda name: "gh")
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs:
                        module.subprocess.CompletedProcess(args[0], 0, "secret-token\n", ""))
    assert module._github_token() == "secret-token"
