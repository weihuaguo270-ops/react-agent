from scripts.ci.harness_stage_scope import declares_stage_completion, inspect_stage_completion


def test_runs_gate_only_when_stage_changes_to_complete():
    base = {"stages": {"P4": {"status": "in_progress"}}}
    head = {"stages": {"P4": {"status": "complete"}}}

    assert declares_stage_completion(base, head, "P4")


def test_does_not_rerun_completed_stage_for_later_changes():
    complete = {"stages": {"P4": {"status": "complete"}}}

    assert not declares_stage_completion(complete, complete, "P4")


def test_does_not_run_for_incomplete_or_removed_stage():
    base = {"stages": {"P4": {"status": "in_progress"}}}
    incomplete = {"stages": {"P4": {"status": "in_progress"}}}
    removed = {"stages": {}}

    assert not declares_stage_completion(base, incomplete, "P4")
    assert not declares_stage_completion(base, removed, "P4")


def test_unreadable_base_or_head_is_blocked(monkeypatch):
    import subprocess

    def fail_diff(*args, **kwargs):
        raise subprocess.CalledProcessError(128, args[0], stderr="bad revision")

    monkeypatch.setattr(subprocess, "run", fail_diff)
    report = inspect_stage_completion("missing-base", "missing-head", "P4")

    assert report["blocked"] is True
    assert report["run"] is False
