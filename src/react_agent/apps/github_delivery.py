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
from typing import TYPE_CHECKING, Any, Sequence
from urllib.parse import urlparse

from react_agent.eval.business_metrics import business_scorecard

if TYPE_CHECKING:
    from react_agent.eval.software_task_runner import SoftwareTaskRunner


EPISODE_SCHEMA_VERSION = "evaluation-episode/v1"
REPORT_SCHEMA_VERSION = "github-delivery-run/v1"
_SAFE_BRANCH = re.compile(r"[^a-zA-Z0-9._/-]+")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# GitHub 远程地址校验。原实现是 `if "github.com" not in source` 子串判断，
# 可被以下形式绕过并把分支推到攻击者主机或内网：
#   https://github.com@127.0.0.1:8765/x.git   （userinfo 里出现 github.com）
#   https://github.com.attacker.tld/x.git     （主机名后缀包含 github.com）
#   ssh://git@github.com.attacker.tld/x.git
# 改为解析后按 host 精确/后缀匹配，且限制 scheme。
_ALLOWED_GIT_SCHEMES = {"https", "ssh", "git"}
_GITHUB_HOSTS = {"github.com", "www.github.com"}


def _require_github_origin(source: str) -> str:
    """校验 origin 指向 GitHub；返回规范化 host，非法则抛 ValueError。"""
    raw = (source or "").strip()
    if not raw:
        raise ValueError("repository origin is empty")

    # scp 形式：git@github.com:owner/repo.git
    scp_like = re.fullmatch(r"(?:[^@/\s]+@)?([^:/\s]+):(.+)", raw)
    if scp_like and "://" not in raw:
        host = scp_like.group(1).lower()
        if host in _GITHUB_HOSTS:
            return host
        raise ValueError(f"repository origin is not GitHub: {host}")

    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_GIT_SCHEMES:
        raise ValueError(f"unsupported git scheme: {scheme or '(none)'}")
    # parsed.hostname 会剥离 userinfo，因此 https://github.com@evil.tld 得到 evil.tld
    host = (parsed.hostname or "").lower()
    if host not in _GITHUB_HOSTS:
        raise ValueError(f"repository origin is not GitHub: {host or '(no host)'}")
    return host


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
    # New task datasets should pin an immutable commit; base_branch remains
    # for backwards-compatible legacy fixtures.
    base_commit: str | None = None
    remote_repository: str | None = None
    allowed_paths: tuple[str, ...] = ()
    hidden_test_command: tuple[str, ...] = ()
    timeout_seconds: int = 600
    max_output_bytes: int = 2_000_000

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
            base_commit=(str(payload["base_commit"]) if payload.get("base_commit") else None),
            remote_repository=(
                str(payload["remote_repository"])
                if payload.get("remote_repository")
                else None
            ),
            allowed_paths=tuple(str(item) for item in payload.get("allowed_paths") or ()),
            hidden_test_command=tuple(str(item) for item in payload.get("hidden_test_command") or ()),
            timeout_seconds=int(payload.get("timeout_seconds", 600)),
            max_output_bytes=int(payload.get("max_output_bytes", 2_000_000)),
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
    software_task_runner: "SoftwareTaskRunner | None" = None
    # P1 default: always attach failure-regression orchestration on delivery exit.
    failure_regression_gate: bool = True
    failure_regression_require_siblings: bool = True
    # P2: optional RepairLoop for hold/test-fail → repair → forced reverify.
    repair_loop: Any = None
    failure_regression_auto_repair: bool = True
    # A2: frozen baseline scan (path or mapping) for true cross-run compare.
    failure_regression_baseline_scan: Any = None


class GitHubDeliveryWorkflow:
    """在隔离克隆中验证变更，审批后才生成候选提交。"""

    def __init__(self, config: WorkflowConfig, *, remote_gateway=None):
        """``remote_gateway`` 是外部写入的注入点：仓库不含内置实现，
        未注入时 Draft PR 走本地 ``gh``。"""
        if config.mode not in {"shadow", "guarded"}:
            raise ValueError("mode must be shadow or guarded")
        self.config = config
        self.config.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.remote_gateway = remote_gateway
        self._active_approval: Approval | None = None

    def _get_remote_gateway(self):
        """返回调用方注入的远程网关（没有则为 None）。

        仓库当前不提供远程网关的 HTTP 客户端实现，因此只能由调用方通过
        ``remote_gateway=`` 注入（测试用 FakeGateway，生产需接入方自行实现）。
        未注入时发布走下方本地 ``gh`` 路径。
        """
        return self.remote_gateway

    def run(
        self,
        task: DeliveryTask,
        *,
        approval: Approval | None = None,
        idempotency_key: str,
        reverify_from: str | Path | None = None,
    ) -> dict[str, Any]:
        """执行一次可审计交付并返回标准化运行报告。

        Shadow 模式只克隆、修改和测试；guarded 模式还要求审批哈希
        与当前计划一致。只有审批显式允许外部写入且配置开启时才会
        推送分支并创建 Draft PR。相同幂等键和计划哈希直接回放报告。

        ``reverify_from`` 指向先前 hold/review 的 failure-regression 目录时，
        走强制复验：未 improved_to_pass 不得成功放行。
        """
        started = time.perf_counter()
        self._active_approval = approval
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
        gate_report: dict[str, Any] = {}
        repair_report: dict[str, Any] = {}
        diff = ""
        commit_sha = ""
        pull_request_url = ""
        error = ""
        parent_reverify = Path(reverify_from).resolve() if reverify_from else None
        did_forced_reverify = parent_reverify is not None

        try:
            # 先完成克隆、修改和验收测试，再允许创建分支或写入远端。
            self._git("clone", "--no-hardlinks", task.repository, str(workspace))
            checkout_ref = task.base_commit or task.base_branch
            self._git("checkout", checkout_ref, cwd=workspace)
            base_commit = self._git("rev-parse", "HEAD", cwd=workspace).stdout.strip()
            steps.append(self._step(1, "clone_repository", {"base": checkout_ref}, "ok"))
            self._apply_replacements(workspace, task.replacements)
            diff = self._git("diff", "--", cwd=workspace).stdout
            if not diff.strip():
                raise ValueError("planned replacements produced no diff")
            steps.append(self._step(2, "apply_candidate_change", {
                "files": [item.path for item in task.replacements],
                "diff_sha256": hashlib.sha256(diff.encode("utf-8")).hexdigest(),
            }, "candidate prepared"))
            if self.config.software_task_runner is not None:
                test_result = self._run_software_task_runner(
                    task, workspace, base_commit=base_commit,
                )
            else:
                test_result = self._run_tests(workspace, task.test_command)
            steps.append(self._step(3, "run_acceptance_tests", {
                "command": list(task.test_command),
                "returncode": test_result["returncode"],
            }, "passed" if test_result["passed"] else "failed"))

            # Optional RepairLoop when acceptance tests fail.
            if (
                not test_result["passed"]
                and self.config.repair_loop is not None
                and self.config.failure_regression_auto_repair
            ):
                repair_report = self._run_repair_loop(task, workspace, test_result)
                steps.append(self._step(3, "repair_loop", {
                    "status": repair_report.get("status"),
                    "attempts": len(repair_report.get("attempts") or []),
                }, str(repair_report.get("status") or "unknown")))
                if repair_report.get("status") == "succeeded":
                    if self.config.software_task_runner is not None:
                        test_result = self._run_software_task_runner(
                            task, workspace, base_commit=base_commit,
                        )
                    else:
                        test_result = self._run_tests(workspace, task.test_command)
                    diff = self._git("diff", "--", cwd=workspace).stdout
                    steps.append(self._step(3, "run_acceptance_tests_after_repair", {
                        "returncode": test_result["returncode"],
                    }, "passed" if test_result["passed"] else "failed"))

            if self.config.failure_regression_gate:
                gate_report = self._run_failure_regression_gate(
                    task=task,
                    run_id=run_id,
                    run_dir=run_dir,
                    steps=steps,
                    test_result=test_result,
                    plan_sha=plan_sha,
                    parent_run_dir=parent_reverify,
                )
                steps.append(self._step(4, "failure_regression_gate", {
                    "release_decision": gate_report.get("release_decision"),
                    "failure_gate_decision": gate_report.get("failure_gate_decision"),
                    "available": gate_report.get("available", True),
                    "reverify": gate_report.get("reverify"),
                }, str(gate_report.get("release_decision") or "unknown")))

                # Same-run: gate hold → optional RepairLoop → forced reverify.
                if (
                    test_result.get("passed")
                    and self._gate_blocks(gate_report)
                    and gate_report.get("available") is not False
                    and parent_reverify is None
                    and self.config.repair_loop is not None
                    and self.config.failure_regression_auto_repair
                ):
                    parent_gate_dir = run_dir / "failure-regression"
                    repair_report = self._run_repair_loop(task, workspace, test_result, gate_report)
                    steps.append(self._step(4, "repair_loop_after_hold", {
                        "status": repair_report.get("status"),
                    }, str(repair_report.get("status") or "unknown")))
                    if repair_report.get("status") == "succeeded":
                        if self.config.software_task_runner is not None:
                            test_result = self._run_software_task_runner(
                                task, workspace, base_commit=base_commit,
                            )
                        else:
                            test_result = self._run_tests(workspace, task.test_command)
                        diff = self._git("diff", "--", cwd=workspace).stdout
                        gate_report = self._run_failure_regression_gate(
                            task=task,
                            run_id=f"{run_id}-reverify",
                            run_dir=run_dir,
                            steps=steps,
                            test_result=test_result,
                            plan_sha=plan_sha,
                            parent_run_dir=parent_gate_dir,
                            out_name="failure-regression-reverify",
                        )
                        did_forced_reverify = True
                        steps.append(self._step(4, "failure_regression_reverify", {
                            "release_decision": gate_report.get("release_decision"),
                            "reverify": gate_report.get("reverify"),
                        }, str(gate_report.get("release_decision") or "unknown")))

            # 验收失败或回归门禁 hold 都是终态，不为未通过的候选变更创建提交。
            if not test_result["passed"]:
                status = "test_failed" if not repair_report else (
                    "repair_failed" if repair_report.get("status") != "succeeded" else "test_failed"
                )
            elif self.config.failure_regression_gate and self._gate_blocks(gate_report):
                if gate_report.get("available") is False:
                    status = "failure_regression_unavailable"
                else:
                    reverify = gate_report.get("reverify") or {}
                    if did_forced_reverify and reverify.get("required") and not reverify.get("improved_to_pass"):
                        status = "failure_regression_reverify_failed"
                    else:
                        status = "failure_regression_hold"
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
                steps.append(self._step(5, "create_candidate_commit", {
                    "branch": branch, "commit_sha": commit_sha,
                }, "committed"))
                if self.config.publish_draft_pr:
                    pull_request_url = self._publish_draft_pr(
                        workspace, task, approval, branch, diff=diff, plan_sha=plan_sha,
                        idempotency_key=idempotency_key,
                    )
                    status = "draft_pr_created"
                    steps.append(self._step(6, "publish_draft_pr", {
                        "url": pull_request_url,
                    }, "published"))
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            error = str(exc)

        duration_ms = round((time.perf_counter() - started) * 1000, 3)
        alerts = self._alerts(status, test_result, duration_ms, gate_report=gate_report)
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
            failure_regression=gate_report,
            repair=repair_report,
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
        for allowed_path in task.allowed_paths:
            path = Path(allowed_path)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"unsafe allowed path: {allowed_path}")
        if task.hidden_test_command and not any(
            tuple(item.lower() for item in task.hidden_test_command)[: len(prefix)] == prefix
            for prefix in self.config.allowed_test_prefixes
        ):
            raise ValueError("hidden test command is outside the allowlist")
        if task.timeout_seconds < 1 or task.max_output_bytes < 1_024:
            raise ValueError("task resource limits are invalid")

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
        """Run the allowlisted test command without shell interpretation.

        Bytecode writing is disabled inside the candidate workspace: CPython records the
        source mtime in ``.pyc`` with one-second resolution and keys validity on
        (mtime, size). A candidate that rewrites a file to the *same size* within the same
        second would otherwise be tested against the previous candidate's bytecode — the
        repair loop then looks flaky because the fix appears not to take effect.
        """
        started = time.perf_counter()
        executable = command[0]
        if executable in {"python", "python3"}:
            executable = os.fspath(Path(os.sys.executable))
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        result = subprocess.run(
            [executable, *command[1:]], cwd=workspace, capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            timeout=self.config.max_test_seconds, shell=False, env=env,
        )
        return {
            "passed": result.returncode == 0,
            "returncode": result.returncode,
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            "stdout_tail": (result.stdout or "")[-4000:],
            "stderr_tail": (result.stderr or "")[-4000:],
        }

    def _run_software_task_runner(
        self,
        task: DeliveryTask,
        workspace: Path,
        *,
        base_commit: str,
    ) -> dict[str, Any]:
        """Run the unified public/hidden contract in the configured Docker gate."""
        from react_agent.eval.software_task import SoftwareTask

        allowed_paths = task.allowed_paths or tuple(
            dict.fromkeys(item.path for item in task.replacements)
        )
        software_task = SoftwareTask(
            task_id=task.task_id,
            repository=task.repository,
            issue_url=task.issue_url,
            base_commit=base_commit,
            split=task.split if task.split in {"dev", "golden", "held_out"} else "dev",
            test_command=task.test_command,
            hidden_test_command=task.hidden_test_command,
            acceptance_criteria=task.acceptance_criteria,
            allowed_paths=allowed_paths,
            timeout_seconds=task.timeout_seconds,
            max_output_bytes=task.max_output_bytes,
            remote_repository=task.remote_repository,
        )
        result = self.config.software_task_runner.run(software_task, workspace=workspace)
        hidden = result.get("hidden_test") or {}
        passed = result.get("status") == "succeeded" and not result.get("gate_blocked")
        return {
            "passed": passed,
            "returncode": result.get("exit_code"),
            "duration_ms": result.get("duration_ms", 0),
            "stdout_tail": result.get("stdout", "")[-4000:],
            "stderr_tail": result.get("stderr", "")[-4000:],
            "runner": "software_task_runner",
            "public_test": result.get("public_test") or {},
            "hidden_test": hidden,
            "changed_paths": result.get("changed_paths") or [],
            "unauthorized_paths": result.get("unauthorized_paths") or [],
            "task_hash": result.get("task_hash", software_task.content_hash()),
            "failure_regression": result.get("failure_regression") or {},
            "software_task_status": result.get("status"),
        }

    def _publish_draft_pr(
        self,
        workspace: Path,
        task: DeliveryTask,
        approval: Approval | None,
        branch: str,
        *,
        diff: str = "",
        plan_sha: str = "",
        idempotency_key: str = "",
    ) -> str:
        """Publish only an already-approved candidate branch as a Draft PR."""
        if approval is None or not approval.allow_external_write:
            raise ValueError("approval does not authorize external writes")
        remote_gateway = self._get_remote_gateway()
        if remote_gateway is not None:
            return remote_gateway.publish_draft_pr(
                repository=task.remote_repository or task.repository,
                base_branch=task.base_branch,
                branch=branch,
                task_id=task.task_id,
                issue_url=task.issue_url,
                diff=diff,
                plan_sha256=plan_sha,
                idempotency_key=idempotency_key,
                approver=approval.approver,
                approved_at=approval.approved_at,
                allow_external_write=approval.allow_external_write,
            )
        if shutil.which("gh") is None:
            raise OSError("gh is required to publish a draft PR")
        source = self._git("-C", task.repository, "remote", "get-url", "origin").stdout.strip()
        _require_github_origin(source)
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

    def _run_repair_loop(
        self,
        task: DeliveryTask,
        workspace: Path,
        test_result: dict[str, Any],
        gate_report: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run injected RepairLoop against the isolated workspace."""
        loop = self.config.repair_loop
        if loop is None:
            return {"status": "skipped"}

        allowed = task.allowed_paths or tuple(
            dict.fromkeys(item.path for item in task.replacements)
        )

        def executor(replacements: Sequence[Any], hidden: bool) -> dict[str, Any]:
            items = tuple(replacements)
            for item in items:
                self._git("checkout", "HEAD", "--", item.path, cwd=workspace)
            self._apply_replacements(workspace, items)
            command = (
                task.hidden_test_command
                if hidden and task.hidden_test_command
                else task.test_command
            )
            return self._run_tests(workspace, command)

        context = {
            "task_id": task.task_id,
            "issue_url": task.issue_url,
            "acceptance_criteria": list(task.acceptance_criteria),
            "failure": {
                "passed": test_result.get("passed"),
                "returncode": test_result.get("returncode"),
                "stdout_tail": test_result.get("stdout_tail"),
                "stderr_tail": test_result.get("stderr_tail"),
            },
            "failure_regression": gate_report or {},
            "repair_feedback": (
                ((gate_report or {}).get("repair_feedback") or {}).get("planner_safe")
                or (gate_report or {}).get("repair_feedback")
                or {}
            ),
        }
        if getattr(loop, "executor", None) is not None and getattr(loop, "planner", None) is not None:
            from react_agent.eval.repair_loop import RepairLoop, RepairLoopConfig

            bound = RepairLoop(
                planner=loop.planner,
                executor=executor,
                allowed_paths=tuple(allowed),
                config=getattr(loop, "config", None) or RepairLoopConfig(),
                observer=getattr(loop, "observer", None),
            )
            return bound.run(context)
        if callable(loop):
            return dict(loop(context, executor))
        return dict(loop.run(context))

    def _run_failure_regression_gate(
        self,
        *,
        task: DeliveryTask,
        run_id: str,
        run_dir: Path,
        steps: list[dict[str, Any]],
        test_result: dict[str, Any],
        plan_sha: str,
        parent_run_dir: Path | None = None,
        out_name: str = "failure-regression",
    ) -> dict[str, Any]:
        """Default hook: Episode → tdebug failure-gate → eval-engine release."""
        from react_agent.eval.failure_regression_gate import (
            evaluate_failure_regression_gate,
            evaluate_forced_reverify,
            mark_reverify_required,
            gate_blocks_success,
        )

        tests_passed = bool(test_result.get("passed"))
        unauthorized = list(test_result.get("unauthorized_paths") or [])
        episode = {
            "schema_version": EPISODE_SCHEMA_VERSION,
            "episode_id": run_id,
            "task": f"Resolve engineering task {task.task_id} from {task.issue_url}",
            "framework": "react-agent-github-delivery",
            "agent_version": "github-delivery-v1",
            "split": task.split if task.split in {"dev", "golden", "held_out", "production"} else "dev",
            "acceptance_criteria": list(task.acceptance_criteria),
            "expected_state": {
                "tests_passed": True,
                "unauthorized_paths_empty": True,
            },
            "final_state": {
                "tests_passed": tests_passed,
                "unauthorized_paths_empty": not unauthorized,
            },
            "trajectory": {
                "session_id": run_id,
                "query": f"Resolve engineering task {task.task_id}",
                "model": "operator-plan-executor-v1",
                "steps": steps,
                "final_answer": f"tests_passed={tests_passed}",
                "metadata": {"issue_url": task.issue_url, "plan_sha256": plan_sha},
            },
        }
        if episode["split"] == "dev":
            episode["split"] = "held_out"
        out_dir = run_dir / out_name
        baseline = self.config.failure_regression_baseline_scan
        if parent_run_dir is not None:
            return evaluate_forced_reverify(
                [episode],
                out_dir=out_dir,
                parent_run_dir=parent_run_dir,
                require_installed_siblings=self.config.failure_regression_require_siblings,
                baseline_scan=baseline,
            )
        report = evaluate_failure_regression_gate(
            [episode],
            out_dir=out_dir,
            require_installed_siblings=self.config.failure_regression_require_siblings,
            baseline_scan=baseline,
        )
        if gate_blocks_success(report):
            report = mark_reverify_required(report, gate_dir=out_dir)
        return report

    @staticmethod
    def _gate_blocks(gate_report: dict[str, Any]) -> bool:
        from react_agent.eval.failure_regression_gate import gate_blocks_success

        return bool(gate_report) and gate_blocks_success(gate_report)

    def _alerts(
        self,
        status: str,
        test_result: dict[str, Any],
        duration_ms: float,
        *,
        gate_report: dict[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        alerts = []
        failed_statuses = {
            "failed",
            "test_failed",
            "repair_failed",
            "failure_regression_hold",
            "failure_regression_unavailable",
            "failure_regression_reverify_failed",
        }
        if status in failed_statuses:
            alerts.append({"severity": "critical", "code": "delivery_failed"})
        if status == "failure_regression_hold":
            alerts.append({"severity": "critical", "code": "failure_regression_hold"})
        if status == "failure_regression_unavailable":
            alerts.append({"severity": "critical", "code": "failure_regression_unavailable"})
        if status == "failure_regression_reverify_failed":
            alerts.append({"severity": "critical", "code": "failure_regression_reverify_failed"})
        if status == "repair_failed":
            alerts.append({"severity": "critical", "code": "repair_failed"})
        if status == "approval_required":
            alerts.append({"severity": "warning", "code": "human_approval_required"})
        if test_result.get("duration_ms", 0) > self.config.max_test_seconds * 1000:
            alerts.append({"severity": "warning", "code": "test_slo_exceeded"})
        if duration_ms > self.config.max_workflow_seconds * 1000:
            alerts.append({"severity": "warning", "code": "workflow_slo_exceeded"})
        if gate_report and gate_report.get("release_decision") == "review":
            alerts.append({"severity": "warning", "code": "failure_regression_review"})
        return alerts

    def _build_report(self, **values: Any) -> dict[str, Any]:
        """Build the cross-repository episode and preserve its evidence boundary."""
        task: DeliveryTask = values["task"]
        success = values["status"] in {"shadow_passed", "candidate_committed", "draft_pr_created"}
        failed_statuses = {
            "failed", "test_failed", "repair_failed",
            "failure_regression_hold", "failure_regression_unavailable",
            "failure_regression_reverify_failed",
        }
        final_state = {
            "status": values["status"],
            "tests_passed": bool(values["test_result"].get("passed")),
            "status_not_failed": values["status"] not in failed_statuses,
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
                    "status_not_failed": values["status"] not in failed_statuses,
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
                "business": business_scorecard(
                    [
                        {
                            "passed": success,
                            "human_handoff": values["status"] == "approval_required",
                            "duration_ms": values["duration_ms"],
                        }
                    ],
                    human_handoff_key="human_handoff",
                    duration_key="duration_ms",
                ),
                "acceptance_test_passed": bool(values["test_result"].get("passed")),
                "rollback_ready": bool(values["commit_sha"]),
                "unauthorized_external_write": bool(
                    values["pull_request_url"]
                    and not (
                        values["approval"]
                        and values["approval"].allow_external_write
                    )
                ),
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
            "failure_regression": values.get("failure_regression") or {},
            "repair": values.get("repair") or {},
            "evidence_boundary": (
                "Local isolated clone and real test subprocess. GitHub is changed only when "
                "publish_draft_pr and an external-write approval are both present. "
                "Failure regression gate is enabled by default and fail-closed without siblings. "
                "After hold/review, success requires forced reverify (reverify_from) proving "
                "improved_to_pass; optional RepairLoop may repair then reverify in-run."
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
