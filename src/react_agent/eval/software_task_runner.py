"""Run a frozen software task in a disposable Docker container.

The runner is intentionally small: cloning and checkout happen before the
container starts, while the test command runs with a read-only root filesystem,
no network, a non-root user, and a single writable workspace mount.
"""
from __future__ import annotations

import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from react_agent.eval.software_task import SoftwareTask


@dataclass(frozen=True)
class SoftwareTaskRunnerConfig:
    runtime: str = "docker"
    image: str = "react-agent-sandbox:0.7.0"
    artifact_dir: Path = Path("artifacts/software-tasks")
    memory: str = "1g"
    cpus: str = "1.0"
    pids_limit: int = 128
    network: str = "none"
    hidden_test_root: Path | None = None
    hidden_test_mount: str = "/hidden-tests"
    public_test_assets: tuple[tuple[Path, str], ...] = ()
    allowed_test_prefixes: tuple[tuple[str, ...], ...] = (
        ("python", "-m", "pytest"),
        ("python3", "-m", "pytest"),
        ("pytest",),
    )
    # P1 default: attach failure-regression gate on SoftwareTask exit.
    failure_regression_gate: bool = True
    failure_regression_require_siblings: bool = True
    # A2: frozen baseline for true cross-run compare (path or mapping).
    failure_regression_baseline_scan: Any = None


def _matches_prefix(command: Sequence[str], prefixes: Sequence[Sequence[str]]) -> bool:
    return any(tuple(command[: len(prefix)]) == tuple(prefix) for prefix in prefixes)


def _path_allowed(path: str, allowed: Sequence[str]) -> bool:
    normalized = path.replace("\\", "/").lstrip("./")
    for prefix in allowed:
        candidate = str(prefix).replace("\\", "/").lstrip("./").rstrip("/")
        if normalized == candidate or normalized.startswith(candidate + "/"):
            return True
    return False


class SoftwareTaskRunner:
    """Clone a task baseline and execute its declared tests in isolation."""

    def __init__(self, config: SoftwareTaskRunnerConfig | None = None):
        self.config = config or SoftwareTaskRunnerConfig()
        if self.config.runtime not in {"docker", "docker.exe"}:
            raise ValueError("runtime must be docker")
        if self.config.network != "none":
            raise ValueError("software task runner requires network=none")
        if not self.config.image or any(ch.isspace() for ch in self.config.image):
            raise ValueError("image is invalid")
        self._runtime_error: str | None = None
        self._runtime_checked = False

    @property
    def executable(self) -> str | None:
        return shutil.which(self.config.runtime)

    def verify_runtime(self) -> tuple[bool, str | None]:
        """Check the CLI, Docker daemon, and local image before execution."""
        if self._runtime_checked:
            return self._runtime_error is None, self._runtime_error
        executable = self.executable
        if not executable:
            self._runtime_error = f"container runtime is unavailable: {self.config.runtime}"
            self._runtime_checked = True
            return False, self._runtime_error
        try:
            info = subprocess.run(
                [executable, "info"], capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=15,
            )
            if info.returncode != 0:
                detail = (info.stderr or info.stdout or "daemon is not ready").strip()
                self._runtime_error = f"container daemon is unavailable: {detail[:300]}"
            else:
                image = subprocess.run(
                    [executable, "image", "inspect", self.config.image],
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=15,
                )
                if image.returncode != 0:
                    detail = (image.stderr or image.stdout or "image not found").strip()
                    self._runtime_error = f"container image unavailable {self.config.image}: {detail[:300]}"
        except (OSError, subprocess.SubprocessError) as exc:
            self._runtime_error = f"container runtime check failed: {exc}"
        self._runtime_checked = True
        return self._runtime_error is None, self._runtime_error

    def validate_commands(self, task: SoftwareTask) -> None:
        for asset, target in self.config.public_test_assets:
            if not Path(asset).is_file():
                raise ValueError(f"public test asset unavailable: {asset}")
            if not target.startswith("tests/") or any(part in {"", ".", ".."} for part in target.split("/")) or "\\" in target or ":" in target:
                raise ValueError("public test target must be a safe tests/ path")
        for name, command in (("test_command", task.test_command), ("hidden_test_command", task.hidden_test_command)):
            if command and not _matches_prefix(command, self.config.allowed_test_prefixes):
                raise ValueError(f"{name} is not in the test command allowlist")
        if task.hidden_test_asset:
            self._hidden_asset_path(task)

    def _hidden_asset_path(self, task: SoftwareTask) -> Path:
        if not task.hidden_test_asset:
            raise ValueError("task has no hidden test asset")
        if self.config.hidden_test_root is None:
            raise ValueError("hidden_test_root is required for hidden_test_asset")
        root = Path(self.config.hidden_test_root).resolve()
        asset = (root / task.hidden_test_asset).resolve()
        if root != asset and root not in asset.parents:
            raise ValueError("hidden test asset escapes hidden_test_root")
        if not asset.exists():
            raise ValueError(f"hidden test asset is unavailable: {task.hidden_test_asset}")
        return asset

    def container_command(
        self,
        task: SoftwareTask,
        workspace: Path,
        name: str,
        command: Sequence[str] | None = None,
    ) -> list[str]:
        """Build a deterministic least-privilege command; does not execute it."""
        command = list(command or task.test_command)
        result = [
            self.config.runtime,
            "run",
            "--rm",
            "--init",
            "--name",
            name,
            "--pull",
            "never",
            "--network",
            self.config.network,
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            str(self.config.pids_limit),
            "--memory",
            self.config.memory,
            "--memory-swap",
            self.config.memory,
            "--cpus",
            self.config.cpus,
            "--user",
            "65532:65532",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=128m",
            "--workdir",
            "/workspace",
            "--volume",
            f"{workspace.resolve()}:/workspace:rw",
            "--env", "PYTHONPATH=/workspace",
            "--env", "PYTEST_ADDOPTS=-p no:cacheprovider",
        ]
        if tuple(command) == task.test_command:
            for asset, target in self.config.public_test_assets:
                result.extend(["--mount", f"type=bind,src={Path(asset).resolve()},dst=/workspace/{target},readonly"])
        if task.hidden_test_asset and tuple(command) == task.hidden_test_command:
            asset = self._hidden_asset_path(task)
            result.extend([
                "--mount",
                f"type=bind,src={asset},dst={self.config.hidden_test_mount}/{asset.name},readonly",
            ])
        return [*result, self.config.image, *command]

    def _clone(self, task: SoftwareTask, workspace: Path) -> None:
        workspace.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--no-hardlinks", task.repository, str(workspace)],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=min(task.timeout_seconds, 300),
        )
        subprocess.run(
            ["git", "checkout", "--detach", task.base_commit],
            cwd=workspace,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=min(task.timeout_seconds, 300),
        )

    def _changed_paths(self, workspace: Path, task: SoftwareTask) -> list[str]:
        result = subprocess.run(
            ["git", "diff", "--name-only", task.base_commit],
            cwd=workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=True,
        )
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def run(self, task: SoftwareTask, *, workspace: Path | None = None, phase: str = "all") -> dict[str, Any]:
        """Execute public tests and return an auditable result envelope.

        ``workspace`` is intended for a pre-created isolated checkout in tests
        or an upstream delivery workflow. If omitted, the runner clones the
        repository into a unique artifact directory.
        """
        if phase not in {"all", "public", "hidden"}:
            raise ValueError("phase must be all, public or hidden")
        if phase == "hidden" and not task.hidden_test_command:
            raise ValueError("hidden test command is required")
        self.validate_commands(task)
        ready, error = self.verify_runtime()
        if not ready:
            raise RuntimeError(error or "container runtime is unavailable")
        executable = self.executable
        assert executable is not None
        if not workspace:
            run_id = f"{task.task_id}-{uuid.uuid4().hex[:10]}"
            workspace = self.config.artifact_dir / "runs" / run_id / "workspace"
            self._clone(task, workspace)
        else:
            workspace = Path(workspace).resolve()
        if not workspace.is_dir():
            raise ValueError(f"workspace does not exist: {workspace}")

        started = time.perf_counter()
        test_results: dict[str, dict[str, Any]] = {}
        combined_stdout: list[str] = []
        combined_stderr: list[str] = []
        final_exit_code: int | None = 0
        status = "succeeded"
        try:
            commands = [("public_test", task.test_command)] if phase != "hidden" else []
            if task.hidden_test_command and phase != "public":
                commands.append(("hidden_test", task.hidden_test_command))
            for label, test_command in commands:
                name = f"react-agent-task-{uuid.uuid4().hex[:12]}"
                command = self.container_command(task, workspace, name, test_command)
                try:
                    result = subprocess.run(
                        [executable, *command[1:]],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=task.timeout_seconds,
                        cwd=workspace,
                    )
                except subprocess.TimeoutExpired as exc:
                    status = "timeout"
                    final_exit_code = None
                    test_results[label] = {
                        "status": "timeout", "returncode": None,
                        "stdout": str(exc.stdout or "")[: task.max_output_bytes],
                        "stderr": str(exc.stderr or "")[: task.max_output_bytes],
                    }
                    break
                stdout = (result.stdout or "")[: task.max_output_bytes]
                stderr = (result.stderr or "")[: task.max_output_bytes]
                test_results[label] = {
                    "status": "passed" if result.returncode == 0 else "failed",
                    "returncode": result.returncode,
                    "stdout": stdout,
                    "stderr": stderr,
                    "stdout_truncated": len(result.stdout or "") > len(stdout),
                    "stderr_truncated": len(result.stderr or "") > len(stderr),
                }
                combined_stdout.append(stdout)
                combined_stderr.append(stderr)
                final_exit_code = result.returncode
                if result.returncode != 0:
                    status = "failed"
                    break

            changed = self._changed_paths(workspace, task)
            unauthorized = [path for path in changed if not _path_allowed(path, task.allowed_paths)]
            if unauthorized:
                status = "failed"
            result = {
                "task_id": task.task_id,
                "task_hash": task.content_hash(),
                "base_commit": task.base_commit,
                "status": status,
                "exit_code": final_exit_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "stdout": "\n".join(combined_stdout)[: task.max_output_bytes],
                "stderr": "\n".join(combined_stderr)[: task.max_output_bytes],
                "public_test": test_results.get("public_test", {}),
                "hidden_test": test_results.get("hidden_test", {}),
                "changed_paths": changed,
                "unauthorized_paths": unauthorized,
                "container": {"runtime": self.config.runtime, "image": self.config.image, "network": self.config.network},
            }
            if self.config.failure_regression_gate:
                from react_agent.eval.failure_regression_gate import attach_software_task_gate

                gate_dir = self.config.artifact_dir / "runs" / f"{task.task_id}-gate" / "failure-regression"
                result = attach_software_task_gate(
                    result,
                    out_dir=gate_dir,
                    task_id=task.task_id,
                    split=getattr(task, "split", "held_out") or "held_out",
                    require_installed_siblings=self.config.failure_regression_require_siblings,
                    baseline_scan=self.config.failure_regression_baseline_scan,
                )
            return result
        finally:
            if 'name' in locals():
                self._remove_container(executable, name)

    @staticmethod
    def _remove_container(executable: str, name: str) -> None:
        """Best-effort cleanup for Docker timeout paths."""
        try:
            subprocess.run(
                [executable, "rm", "--force", name], capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            pass


__all__ = ["SoftwareTaskRunner", "SoftwareTaskRunnerConfig"]
