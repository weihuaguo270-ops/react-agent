"""RepairLoop 的软件任务执行器适配层。"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any
from pathlib import Path
from tempfile import TemporaryDirectory


class SoftwareTaskExecutor:
    """将补丁应用与测试委托给调用方提供的函数。

    apply_patch 和 run_tests 可由现有 SoftwareTaskRunner 或 Docker runner 注入，
    因此执行器不绑定容器、测试框架或模型实现。
    """

    def __init__(
        self,
        apply_patch: Callable[[tuple[Any, ...]], Mapping[str, Any]],
        run_tests: Callable[[bool], Mapping[str, Any]],
    ) -> None:
        self._apply_patch = apply_patch
        self._run_tests = run_tests

    def __call__(self, replacements: tuple[Any, ...], hidden: bool) -> Mapping[str, Any]:
        applied = dict(self._apply_patch(replacements))
        if applied.get("applied") is False:
            return {"passed": False, "failed_test": "patch_application", **applied}
        result = dict(self._run_tests(hidden))
        return {**result, "changed_paths": [getattr(item, "path", "") for item in replacements]}


__all__ = ["SoftwareTaskExecutor"]


class DockerTaskExecutor:
    """在一个固定 Docker Runner 工作区中应用补丁并分阶段执行测试。"""
    def __init__(self, task: Any, runner: Any) -> None:
        self.task, self.runner = task, runner
        self._tmp = TemporaryDirectory(prefix="react-agent-docker-task-")
        self.workspace = Path(self._tmp.name) / "workspace"
        runner._clone(task, self.workspace)

    def __call__(self, replacements: tuple[Any, ...], hidden: bool) -> Mapping[str, Any]:
        for item in replacements:
            target = self.workspace / item.path
            text = target.read_text(encoding="utf-8")
            if item.old in text:
                target.write_text(text.replace(item.old, item.new, 1), encoding="utf-8")
            elif item.new not in text:
                return {"passed": False, "failed_test": "patch_application", "applied": False,
                        "error": f"old text not found: {item.path}"}
        result = self.runner.run(self.task, workspace=self.workspace, phase="hidden" if hidden else "public")
        return {"passed": result.get("status") == "succeeded", "returncode": result.get("exit_code"),
                "stdout_tail": result.get("stdout", "")[-4000:], "stderr_tail": result.get("stderr", "")[-4000:],
                "changed_paths": result.get("changed_paths", [])}

    def close(self) -> None:
        self._tmp.cleanup()


__all__.append("DockerTaskExecutor")
