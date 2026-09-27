"""将 Agent 的结构化补丁计划转换为受控交付替换。"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .github_delivery import Replacement


class PatchPlanError(ValueError):
    """补丁计划不满足安全或结构约束。"""


def parse_patch_plan(payload: Mapping[str, Any], *, allowed_paths: Sequence[str]) -> tuple[Replacement, ...]:
    """校验模型输出，不执行文件写入。"""
    raw = payload.get("replacements")
    if not isinstance(raw, list) or not raw:
        raise PatchPlanError("replacements must be a non-empty array")
    allowed = tuple(str(item).replace("\\", "/").rstrip("/") for item in allowed_paths)
    if not allowed:
        raise PatchPlanError("allowed_paths must be non-empty")
    result: list[Replacement] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise PatchPlanError(f"replacements[{index}] must be an object")
        path = str(item.get("path", "")).replace("\\", "/")
        old = item.get("old")
        new = item.get("new")
        if not path or not isinstance(old, str) or not old or not isinstance(new, str):
            raise PatchPlanError(f"replacements[{index}] requires path, old and new")
        candidate = Path(path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise PatchPlanError(f"unsafe replacement path: {path}")
        if not any(path == prefix or path.startswith(prefix + "/") for prefix in allowed):
            raise PatchPlanError(f"replacement path is outside allowed_paths: {path}")
        result.append(Replacement(path, old, new))
    return tuple(result)


__all__ = ["PatchPlanError", "parse_patch_plan"]
