import json
import subprocess
from pathlib import Path

import pytest

from react_agent.apps.github_delivery import (
    Approval,
    DeliveryTask,
    GitHubDeliveryWorkflow,
    Replacement,
    WorkflowConfig,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _repository(tmp_path: Path) -> Path:
    repo = tmp_path / "service"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "test")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "service.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "test_service.py").write_text(
        "from service import VALUE\n\ndef test_value():\n    assert VALUE == 2\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture")
    return repo


def _task(repo: Path) -> DeliveryTask:
    return DeliveryTask(
        task_id="issue-17",
        repository=str(repo),
        issue_url="local://issues/17",
        split="held_out",
        replacements=(Replacement("service.py", "VALUE = 1", "VALUE = 2"),),
        test_command=("python", "-m", "pytest", "-q"),
        acceptance_criteria=("tests pass", "base branch remains unchanged"),
    )


def test_shadow_run_is_real_but_does_not_modify_source(tmp_path):
    repo = _repository(tmp_path)
    workflow = GitHubDeliveryWorkflow(WorkflowConfig(tmp_path / "artifacts"))
    report = workflow.run(_task(repo), idempotency_key="shadow-17")

    assert report["status"] == "shadow_passed"
    assert report["test_result"]["passed"] is True
    assert report["episode"]["state_verification"]["passed"] is True
    assert report["episode"]["task"].startswith("Resolve engineering task")
    assert report["episode"]["final_state"]["status_not_failed"] is True
    assert (repo / "service.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert (tmp_path / "artifacts" / "audit.jsonl").exists()


def test_guarded_run_requires_approval_bound_to_plan(tmp_path):
    repo = _repository(tmp_path)
    task = _task(repo)
    workflow = GitHubDeliveryWorkflow(WorkflowConfig(tmp_path / "artifacts", mode="guarded"))

    pending = workflow.run(task, idempotency_key="guarded-missing")
    assert pending["status"] == "approval_required"
    assert pending["candidate_commit"] == ""

    approval = Approval(
        plan_sha256=pending["plan_sha256"],
        approver="reviewer@example.com",
        approved_at="2026-08-14T00:00:00+00:00",
    )
    approved = workflow.run(task, approval=approval, idempotency_key="guarded-approved")
    assert approved["status"] == "candidate_committed"
    assert approved["candidate_commit"]
    assert approved["rollback"]["ready"] is True


def test_idempotency_replays_and_rejects_key_reuse(tmp_path):
    repo = _repository(tmp_path)
    workflow = GitHubDeliveryWorkflow(WorkflowConfig(tmp_path / "artifacts"))
    task = _task(repo)
    first = workflow.run(task, idempotency_key="same-key")
    second = workflow.run(task, idempotency_key="same-key")
    assert second["run_id"] == first["run_id"]
    assert second["idempotent_replay"] is True
    ledger = (tmp_path / "artifacts" / "idempotency.json").read_text(encoding="utf-8")
    assert str(tmp_path) not in ledger

    changed = DeliveryTask(**{**task.__dict__, "task_id": "issue-18"})
    with pytest.raises(ValueError, match="another plan"):
        workflow.run(changed, idempotency_key="same-key")


def test_task_rejects_path_escape_and_arbitrary_command(tmp_path):
    repo = _repository(tmp_path)
    workflow = GitHubDeliveryWorkflow(WorkflowConfig(tmp_path / "artifacts"))
    task = _task(repo)
    unsafe = DeliveryTask(**{
        **task.__dict__,
        "replacements": (Replacement("../outside.py", "x", "y"),),
    })
    with pytest.raises(ValueError, match="unsafe replacement path"):
        workflow.run(unsafe, idempotency_key="unsafe-path")

    arbitrary = DeliveryTask(**{**task.__dict__, "test_command": ("powershell", "whoami")})
    with pytest.raises(ValueError, match="allowlist"):
        workflow.run(arbitrary, idempotency_key="unsafe-command")


def test_report_episode_can_be_saved_independently(tmp_path):
    repo = _repository(tmp_path)
    workflow = GitHubDeliveryWorkflow(WorkflowConfig(tmp_path / "artifacts"))
    report = workflow.run(_task(repo), idempotency_key="episode")
    episode_path = tmp_path / "episode.json"
    episode_path.write_text(json.dumps(report["episode"]), encoding="utf-8")
    payload = json.loads(episode_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "evaluation-episode/v1"
    assert payload["split"] == "held_out"
