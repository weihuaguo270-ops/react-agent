"""工程 Agent 的影子验证、审批和候选变更交付流程。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


EPISODE_SCHEMA_VERSION = "evaluation-episode/v1"
REPORT_SCHEMA_VERSION = "github-delivery-run/v1"
_SAFE_BRANCH = re.compile(r"[^a-zA-Z0-9._/-]+")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_hash(payload: Any) -> str:
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Replacement:
    """一次受控的精确文本替换，不支持模糊匹配。"""

    path: str
    old: str
    new: str


@dataclass(frozen=True)
class DeliveryTask:
    """可哈希、可回放的工程交付计划。"""

    task_id: str
    repository: str
    issue_url: str
    split: str
    replacements: tuple[Replacement, ...]
    test_command: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    base_branch: str = "HEAD"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DeliveryTask":
        """从持久化任务载荷恢复交付计划。"""
        return cls(
            task_id=str(payload["task_id"]),
            repository=str(payload["repository"]),
            issue_url=str(payload["issue_url"]),
            split=str(payload.get("split") or "dev"),
            replacements=tuple(Replacement(**item) for item in payload["replacements"]),
            test_command=tuple(str(item) for item in payload["test_command"]),
            acceptance_criteria=tuple(str(item) for item in payload["acceptance_criteria"]),
            base_branch=str(payload.get("base_branch") or "HEAD"),
        )

    def plan_payload(self) -> dict[str, Any]:
        """返回参与审批哈希计算的完整计划内容。"""
        return asdict(self)


@dataclass(frozen=True)
class Approval:
    """绑定计划哈希的人工审批凭据。"""

    plan_sha256: str
    approver: str
    approved_at: str
    allow_external_write: bool = False

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Approval":
        """从控制面记录恢复审批凭据。"""
        return cls(
            plan_sha256=str(payload["plan_sha256"]),
            approver=str(payload["approver"]),
            approved_at=str(payload["approved_at"]),
            allow_external_write=bool(payload.get("allow_external_write", False)),
        )


@dataclass(frozen=True)
class WorkflowConfig:
    """交付运行模式、证据目录和资源上限。"""

    artifact_dir: Path
    mode: str = "shadow"
    publish_draft_pr: bool = False
    max_test_seconds: int = 120
    max_workflow_seconds: int = 300
    allowed_test_prefixes: tuple[tuple[str, ...], ...] = (
        ("python", "-m", "pytest"),
        ("python3", "-m", "pytest"),
        ("pytest",),
    )


class GitHubDeliveryWorkflow:
    """在隔离克隆中验证变更，审批后才生成候选提交。"""

    def __init__(self, config: WorkflowConfig):
        if config.mode not in {"shadow", "guarded"}:
            raise ValueError("mode must be shadow or guarded")
        self.config = config
        self.config.artifact_dir.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        task: DeliveryTask,
        *,
        approval: Approval | None = None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """执行一次可审计交付并返回标准化运行报告。

        Shadow 模式只克隆、修改和测试；guarded 模式还要求审批哈希
        与当前计划一致。只有审批显式允许外部写入且配置开启时才会
        推送分支并创建 Draft PR。相同幂等键和计划哈希直接回放报告。
        """
        started = time.perf_counter()
        plan_sha = _json_hash(task.plan_payload())
        replay = self._load_replay(idempotency_key, plan_sha)
        if replay is not None:
            replay["idempotent_replay"] = True
            return replay

        self._validate_task(task)
        approval_state = self._validate_approval(plan_sha, approval)
        run_id = f"{task.task_id}-{uuid.uuid4().hex[:10]}"
        run_dir = self.config.artifact_dir / "runs" / run_id
        workspace = run_dir / "workspace"
        run_dir.mkdir(parents=True)
        steps: list[dict[str, Any]] = []
        status = "failed"
        test_result: dict[str, Any] = {}
        diff = ""
        commit_sha = ""
        pull_request_url = ""
        error = ""

        try:
            # Clone, edit and test finish before any branch or remote write.
            self._git("clone", "--no-hardlinks", task.repository, str(workspace))
            self._git("checkout", task.base_branch, cwd=workspace)
            steps.append(self._step(1, "clone_repository", {"base": task.base_branch}, "ok"))
            self._apply_replacements(workspace, task.replacements)
            diff = self._git("diff", "--", cwd=workspace).stdout
            if not diff.strip():
                raise ValueError("planned replacements produced no diff")
            steps.append(self._step(2, "apply_candidate_change", {
                "files": [item.path for item in task.replacements],
                "diff_sha256": hashlib.sha256(diff.encode("utf-8")).hexdigest(),
            }, "candidate prepared"))
            test_result = self._run_tests(workspace, task.test_command)
            steps.append(self._step(3, "run_acceptance_tests", {
                "command": list(task.test_command),
                "returncode": test_result["returncode"],
            }, "passed" if test_result["passed"] else "failed"))

            # A failed acceptance test is terminal; never write a rejected candidate.
            if not test_result["passed"]:
                status = "test_failed"
            elif self.config.mode == "shadow":
                status = "shadow_passed"
            elif approval_state != "approved":
                status = "approval_required"
            else:
                branch = self._branch_name(task.task_id)
                self._git("checkout", "-b", branch, cwd=workspace)
                self._git("add", "--", *[item.path for item in task.replacements], cwd=workspace)
                self._git(
                    "-c", "user.name=react-agent",
                    "-c", "user.email=react-agent@localhost",
                    "commit", "-m", f"agent: resolve {task.task_id}", cwd=workspace,
                )
                commit_sha = self._git("rev-parse", "HEAD", cwd=workspace).stdout.strip()
                status = "candidate_committed"
                steps.append(self._step(4, "create_candidate_commit", {
                    "branch": branch, "commit_sha": commit_sha,
                }, "committed"))
                if self.config.publish_draft_pr:
                    pull_request_url = self._publish_draft_pr(workspace, task, approval, branch)
                    status = "draft_pr_created"
                    steps.append(self._step(5, "publish_draft_pr", {
                        "url": pull_request_url,
                    }, "published"))
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            error = str(exc)

        duration_ms = round((time.perf_counter() - started) * 1000, 3)
        alerts = self._alerts(status, test_result, duration_ms)
        report = self._build_report(
            task=task,
            run_id=run_id,
            plan_sha=plan_sha,
            approval_state=approval_state,
            approval=approval,
            status=status,
            duration_ms=duration_ms,
            test_result=test_result,
            diff=diff,
            commit_sha=commit_sha,
            pull_request_url=pull_request_url,
            steps=steps,
            alerts=alerts,
            error=error,
        )
        report_path = run_dir / "report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self._append_audit(report, report_path)
        self._store_replay(idempotency_key, plan_sha, report_path)
        return report

    def _validate_task(self, task: DeliveryTask) -> None:
        """Validate inputs that can affect the isolated worktree."""
        repository = Path(task.repository).resolve()
        if not repository.is_dir() or not (repository / ".git").exists():
            raise ValueError("repository must be a local Git worktree")
        if not task.task_id or not task.issue_url.startswith(("https://github.com/", "local://")):
            raise ValueError("task_id and a traceable issue_url are required")
        if task.split not in {"dev", "golden", "held_out", "production"}:
            raise ValueError("unsupported split")
        if not task.replacements or not task.test_command or not task.acceptance_criteria:
            raise ValueError("replacements, test_command and acceptance_criteria are required")
        command = tuple(item.lower() for item in task.test_command)
        if not any(command[: len(prefix)] == prefix for prefix in self.config.allowed_test_prefixes):
            raise ValueError("test command is outside the allowlist")
        for replacement in task.replacements:
            path = Path(replacement.path)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"unsafe replacement path: {replacement.path}")

    def _validate_approval(self, plan_sha: str, approval: Approval | None) -> str:
        """Treat malformed or mismatched approval records as non-consent."""
        if self.config.mode == "shadow":
            return "not_required"
        if approval is None:
            return "missing"
        try:
            datetime.fromisoformat(approval.approved_at.replace("Z", "+00:00"))
        except ValueError:
            return "invalid"
        if not approval.approver.strip() or approval.plan_sha256 != plan_sha:
            return "invalid"
        return "approved"

    def _apply_replacements(self, workspace: Path, replacements: Sequence[Replacement]) -> None:
        root = workspace.resolve()
        for replacement in replacements:
            target = (workspace / replacement.path).resolve()
            if root not in target.parents:
                raise ValueError(f"replacement escapes workspace: {replacement.path}")
            content = target.read_text(encoding="utf-8")
            occurrences = content.count(replacement.old)
            if occurrences != 1:
                raise ValueError(f"expected one match in {replacement.path}, found {occurrences}")
            target.write_text(content.replace(replacement.old, replacement.new), encoding="utf-8")

    def _run_tests(self, workspace: Path, command: Sequence[str]) -> dict[str, Any]:
        """Run the allowlisted test command without shell interpretation."""
        started = time.perf_counter()
        executable = command[0]
        if executable in {"python", "python3"}:
            executable = os.fspath(Path(os.sys.executable))
        result = subprocess.run(
            [executable, *command[1:]], cwd=workspace, capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            timeout=self.config.max_test_seconds, shell=False,
        )
        return {
            "passed": result.returncode == 0,
            "returncode": result.returncode,
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            "stdout_tail": (result.stdout or "")[-4000:],
            "stderr_tail": (result.stderr or "")[-4000:],
        }

    def _publish_draft_pr(
        self, workspace: Path, task: DeliveryTask, approval: Approval | None, branch: str
    ) -> str:
        """Publish only an already-approved candidate branch as a Draft PR."""
        if approval is None or not approval.allow_external_write:
            raise ValueError("approval does not authorize external writes")
        if shutil.which("gh") is None:
            raise OSError("gh is required to publish a draft PR")
        source = self._git("-C", task.repository, "remote", "get-url", "origin").stdout.strip()
        if "github.com" not in source:
            raise ValueError("repository origin is not GitHub")
        self._git("remote", "set-url", "origin", source, cwd=workspace)
        self._git("push", "origin", f"HEAD:refs/heads/{branch}", cwd=workspace)
        result = subprocess.run(
            ["gh", "pr", "create", "--draft", "--title", f"Agent: {task.task_id}",
             "--body", f"Source task: {task.issue_url}\n\nPlan: `{_json_hash(task.plan_payload())}`",
             "--head", branch],
            cwd=workspace, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=60, shell=False,
        )
        if result.returncode != 0:
            raise subprocess.CalledProcessError(result.returncode, result.args, result.stdout, result.stderr)
        return result.stdout.strip()

    def _alerts(self, status: str, test_result: dict[str, Any], duration_ms: float) -> list[dict[str, str]]:
        alerts = []
        if status in {"failed", "test_failed"}:
            alerts.append({"severity": "critical", "code": "delivery_failed"})
        if status == "approval_required":
            alerts.append({"severity": "warning", "code": "human_approval_required"})
        if test_result.get("duration_ms", 0) > self.config.max_test_seconds * 1000:
            alerts.append({"severity": "warning", "code": "test_slo_exceeded"})
        if duration_ms > self.config.max_workflow_seconds * 1000:
            alerts.append({"severity": "warning", "code": "workflow_slo_exceeded"})
        return alerts

    def _build_report(self, **values: Any) -> dict[str, Any]:
        """Build the cross-repository episode and preserve its evidence boundary."""
        task: DeliveryTask = values["task"]
        success = values["status"] in {"shadow_passed", "candidate_committed", "draft_pr_created"}
        final_state = {
            "status": values["status"],
            "tests_passed": bool(values["test_result"].get("passed")),
            "status_not_failed": values["status"] not in {"failed", "test_failed"},
            "external_write": bool(values["pull_request_url"]),
            "candidate_commit": values["commit_sha"],
        }
        episode = {
            "schema_version": EPISODE_SCHEMA_VERSION,
            "episode_id": values["run_id"],
            "task": f"Resolve engineering task {task.task_id} from {task.issue_url}",
            "framework": "react-agent-github-delivery",
            "agent_version": "github-delivery-v1",
            "split": task.split,
            "acceptance_criteria": list(task.acceptance_criteria),
            "expected_state": {"tests_passed": True, "status_not_failed": True},
            "final_state": final_state,
            "state_verification": {
                "passed": success,
                "checks": {
                    "tests_passed": bool(values["test_result"].get("passed")),
                    "status_not_failed": values["status"] not in {"failed", "test_failed"},
                },
            },
            "trajectory": {
                "session_id": values["run_id"],
                "query": f"Resolve engineering task {task.task_id}",
                "model": "operator-plan-executor-v1",
                "steps": values["steps"],
                "final_answer": f"delivery status: {values['status']}",
                "metadata": {"issue_url": task.issue_url, "plan_sha256": values["plan_sha"]},
            },
        }
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "evidence_level": "local_real",
            "run_id": values["run_id"],
            "generated_at": _utc_now(),
            "task_id": task.task_id,
            "issue_url": task.issue_url,
            "mode": self.config.mode,
            "status": values["status"],
            "passed": success,
            "plan_sha256": values["plan_sha"],
            "approval": {
                "state": values["approval_state"],
                "approver": values["approval"].approver if values["approval"] else "",
                "approved_at": values["approval"].approved_at if values["approval"] else "",
                "external_write_authorized": bool(
                    values["approval"] and values["approval"].allow_external_write
                ),
            },
            "metrics": {
                "workflow_duration_ms": values["duration_ms"],
                "test_duration_ms": values["test_result"].get("duration_ms"),
                "human_takeover_required": values["status"] == "approval_required",
                "external_write_count": int(bool(values["pull_request_url"])),
            },
            "test_result": values["test_result"],
            "diff_sha256": hashlib.sha256(values["diff"].encode("utf-8")).hexdigest() if values["diff"] else "",
            "candidate_commit": values["commit_sha"],
            "pull_request_url": values["pull_request_url"],
            "rollback": {
                "ready": bool(values["commit_sha"]),
                "strategy": "close draft PR and delete candidate branch; base branch is never modified",
            },
            "alerts": values["alerts"],
            "incident": {
                "review_required": bool(values["alerts"]),
                "feedback_episode_id": values["run_id"] if values["alerts"] else "",
            },
            "error": values["error"],
            "episode": episode,
            "evidence_boundary": (
                "Local isolated clone and real test subprocess. GitHub is changed only when "
                "publish_draft_pr and an external-write approval are both present."
            ),
        }

    @staticmethod
    def _step(number: int, name: str, arguments: dict[str, Any], observation: str) -> dict[str, Any]:
        return {
            "step": number,
            "thought": f"Execute controlled delivery stage: {name}.",
            "action": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
            "observation": observation,
        }

    @staticmethod
    def _branch_name(task_id: str) -> str:
        cleaned = _SAFE_BRANCH.sub("-", task_id).strip("-./") or "task"
        return f"agent/{cleaned[:80]}"

    @staticmethod
    def _git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120, shell=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "git command failed").strip()
            raise subprocess.CalledProcessError(result.returncode, result.args, result.stdout, detail)
        return result

    @property
    def _ledger_path(self) -> Path:
        return self.config.artifact_dir / "idempotency.json"

    def _load_replay(self, key: str, plan_sha: str) -> dict[str, Any] | None:
        if not key:
            raise ValueError("idempotency_key is required")
        if not self._ledger_path.exists():
            return None
        ledger = json.loads(self._ledger_path.read_text(encoding="utf-8"))
        entry = ledger.get(key)
        if not entry:
            return None
        if entry["plan_sha256"] != plan_sha:
            raise ValueError("idempotency_key already belongs to another plan")
        report_path = Path(entry["report_path"])
        if not report_path.is_absolute():
            report_path = self.config.artifact_dir / report_path
        return json.loads(report_path.read_text(encoding="utf-8"))

    def _store_replay(self, key: str, plan_sha: str, report_path: Path) -> None:
        ledger = {}
        if self._ledger_path.exists():
            ledger = json.loads(self._ledger_path.read_text(encoding="utf-8"))
        relative_path = report_path.resolve().relative_to(self.config.artifact_dir.resolve())
        ledger[key] = {"plan_sha256": plan_sha, "report_path": relative_path.as_posix()}
        self._ledger_path.write_text(
            json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def _append_audit(self, report: dict[str, Any], report_path: Path) -> None:
        event = {
            "timestamp": _utc_now(),
            "run_id": report["run_id"],
            "task_id": report["task_id"],
            "mode": report["mode"],
            "status": report["status"],
            "plan_sha256": report["plan_sha256"],
            "report_path": report_path.resolve().relative_to(
                self.config.artifact_dir.resolve()
            ).as_posix(),
        }
        with (self.config.artifact_dir / "audit.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")


__all__ = ["Approval", "DeliveryTask", "GitHubDeliveryWorkflow", "Replacement", "WorkflowConfig"]
