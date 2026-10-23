from __future__ import annotations

import subprocess

import pytest

from scripts.ci import check_pr_ready


def test_changed_files_includes_worktree_and_untracked_files(monkeypatch):
    outputs = {
        ("git", "diff", "--name-only", "HEAD"): "staged.txt\nunstaged.txt\n",
        ("git", "ls-files", "--others", "--exclude-standard"): "new.txt\n",
    }

    def fake_run(*args: str, check: bool = True):
        return subprocess.CompletedProcess(args, 0, outputs[args], "")

    monkeypatch.setattr(check_pr_ready, "run", fake_run)

    assert check_pr_ready.changed_files(None) == ["new.txt", "staged.txt", "unstaged.txt"]


def test_changed_files_combines_base_diff_and_worktree(monkeypatch):
    outputs = {
        ("git", "diff", "--name-only", "origin/main...HEAD"): "committed.txt\nshared.txt\n",
        ("git", "diff", "--name-only", "HEAD"): "shared.txt\nworking.txt\n",
        ("git", "ls-files", "--others", "--exclude-standard"): "new.txt\n",
    }

    def fake_run(*args: str, check: bool = True):
        return subprocess.CompletedProcess(args, 0, outputs[args], "")

    monkeypatch.setattr(check_pr_ready, "run", fake_run)

    assert check_pr_ready.changed_files("origin/main") == [
        "committed.txt",
        "new.txt",
        "shared.txt",
        "working.txt",
    ]


def test_changed_files_fails_closed_when_git_cannot_enumerate(monkeypatch):
    def fake_run(*args: str, check: bool = True):
        return subprocess.CompletedProcess(args, 128, "", "bad revision")

    monkeypatch.setattr(check_pr_ready, "run", fake_run)

    with pytest.raises(RuntimeError, match="unable to enumerate changed files"):
        check_pr_ready.changed_files("missing-base")


def test_resolve_base_refs_fails_closed_without_explicit_or_remote_base(monkeypatch):
    monkeypatch.setattr(check_pr_ready, "git", lambda *args, **kwargs: "")

    with pytest.raises(RuntimeError, match="no base ref available"):
        check_pr_ready.resolve_base_refs(None, ci=False)


def test_resolve_base_refs_accepts_explicit_base_without_remote(monkeypatch):
    monkeypatch.setattr(check_pr_ready, "git", lambda *args, **kwargs: "")

    assert check_pr_ready.resolve_base_refs("HEAD~3", ci=False) == ["HEAD~3"]


def test_main_fails_when_no_base_is_available(monkeypatch, capsys):
    def fake_git(*args: str, check: bool = True):
        if args == ("log", "-1", "--pretty=%s"):
            return "fix: test missing base"
        return ""

    def fake_run(*args: str, check: bool = True):
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(check_pr_ready, "git", fake_git)
    monkeypatch.setattr(check_pr_ready, "run", fake_run)
    monkeypatch.setattr(check_pr_ready, "check_corpus", lambda failures, *, strict: None)

    assert check_pr_ready.main([]) == 1
    output = capsys.readouterr()
    assert "no base ref available" in output.err
    assert "PR READY: FAIL" in output.err
