"""统一任务执行环境诊断。"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


def _command(*args: str) -> dict[str, Any]:
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=20)
        return {"ok": p.returncode == 0, "returncode": p.returncode,
                "stdout": p.stdout[-1000:], "stderr": p.stderr[-1000:]}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "error": str(exc)}


def diagnose(*, project_root: str | Path, image: str, hidden_root: str | Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    hidden = Path(hidden_root).resolve()
    return {
        "python": {"executable": shutil.which("python"), "version": _command("python", "--version")},
        "docker": {"context": os.getenv("DOCKER_CONTEXT", "default"), "info": _command("docker", "info", "--format", "{{.ServerVersion}}")},
        "image": _command("docker", "image", "inspect", image, "--format", "{{.Id}}"),
        "deepseek_key_configured": bool(os.getenv("DEEPSEEK_API_KEY")),
        "project_root": str(root),
        "hidden_root_exists": hidden.is_dir(),
        "pytest": _command("python", "-m", "pytest", "--version"),
    }


__all__ = ["diagnose"]
