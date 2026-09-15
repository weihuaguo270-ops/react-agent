"""基于 git worktree 的受控软件任务 Runner。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Sequence


class IsolatedTaskRunner:
    def __init__(self, repository: str | Path, base_commit: str, public_command: Sequence[str], hidden_command: Sequence[str], allowed_paths: Sequence[str], timeout: int = 300) -> None:
        self.repository = Path(repository)
        self.base_commit = base_commit
        self.public_command = tuple(public_command)
        self.hidden_command = tuple(hidden_command)
        self.allowed_paths = tuple(allowed_paths)
        self.timeout = timeout
        self.workspace: Path | None = None

    def _run(self, command: Sequence[str]) -> dict[str, Any]:
        command = list(command)
        if command and command[0] in {"python", "python3"}:
            command[0] = sys.executable
        p = subprocess.run(command, cwd=self.workspace, text=True, capture_output=True, timeout=self.timeout)
        return {"passed": p.returncode == 0, "returncode": p.returncode,
                "stdout_tail": p.stdout[-4000:], "stderr_tail": p.stderr[-4000:]}

    def apply_patch(self, replacements: tuple[Any, ...]) -> dict[str, Any]:
        if self.workspace is None:
            return {"applied": False, "error": "workspace is not initialized"}
        for item in replacements:
            path = Path(item.path)
            normalized = path.as_posix()
            allowed = tuple(str(item).replace("\\", "/").rstrip("/") for item in self.allowed_paths)
            if path.is_absolute() or ".." in path.parts or not any(normalized == x or normalized.startswith(x + "/") for x in allowed):
                return {"applied": False, "error": f"path not allowed: {item.path}"}
            target = self.workspace / path
            text = target.read_text(encoding="utf-8")
            if item.old not in text:
                if item.new in text:
                    continue
                return {"applied": False, "error": f"old text not found: {item.path}"}
            target.write_text(text.replace(item.old, item.new, 1), encoding="utf-8")
        return {"applied": True}

    def run_tests(self, hidden: bool) -> dict[str, Any]:
        return self._run(self.hidden_command if hidden else self.public_command)

    def __enter__(self) -> "IsolatedTaskRunner":
        self._tmp = TemporaryDirectory(prefix="react-agent-task-")
        self.workspace = Path(self._tmp.name) / "repo"
        subprocess.run(["git", "clone", "--no-checkout", str(self.repository), str(self.workspace)], check=True, capture_output=True)
        subprocess.run(["git", "checkout", self.base_commit], cwd=self.workspace, check=True, capture_output=True)
        return self

    def __exit__(self, *_: object) -> None:
        self._tmp.cleanup()


__all__ = ["IsolatedTaskRunner"]
