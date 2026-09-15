"""从软件任务 manifest 构造隔离 Runner。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .software_task import SoftwareTask
from .software_task_runner import SoftwareTaskRunner, SoftwareTaskRunnerConfig


def load_tasks(path: str | Path) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    tasks = data.get("tasks", [])
    if not isinstance(tasks, list):
        raise ValueError("manifest.tasks must be a list")
    return tasks


def build_runner(task: dict[str, Any], repository: str | Path, *, artifact_root: str | Path) -> tuple[SoftwareTask, SoftwareTaskRunner]:
    required = ("base_commit", "test_command", "hidden_test_command", "allowed_paths")
    missing = [key for key in required if key not in task]
    if missing:
        raise ValueError(f"task missing fields: {', '.join(missing)}")
    normalized = dict(task)
    normalized["repository"] = str(Path(repository).resolve())
    software_task = SoftwareTask.from_dict(normalized)
    root = Path(artifact_root).resolve()
    test_name = Path(task["test_command"][-1]).name
    review_asset = _resolve_public_test_asset(root, task, test_name)
    hidden_root = root / "hidden-assets"
    config = SoftwareTaskRunnerConfig(
        runtime="docker", image=task.get("build", {}).get("runtime_image", "react-agent-review-fastapi-15764:20260912e"),
        artifact_dir=root.parent, hidden_test_root=hidden_root,
        public_test_assets=((review_asset, task["test_command"][-1]),) if review_asset is not None else (),
    )
    return software_task, SoftwareTaskRunner(config)


def _resolve_public_test_asset(root: Path, task: dict[str, Any], test_name: str) -> Path | None:
    """Locate review public tests; folders use short ids (fastapi-16253), not full task_id."""
    candidates: list[Path] = [root / "review" / task["task_id"] / "tests" / test_name]
    hidden_asset = str(task.get("hidden_test_asset") or "").replace("\\", "/").strip("/")
    if hidden_asset and "/" in hidden_asset:
        candidates.append(root / "review" / hidden_asset.split("/", 1)[0] / "tests" / test_name)
    parts = str(task["task_id"]).split("-")
    if len(parts) >= 2:
        candidates.append(root / "review" / f"{parts[0]}-{parts[1]}" / "tests" / test_name)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


__all__ = ["load_tasks", "build_runner"]
