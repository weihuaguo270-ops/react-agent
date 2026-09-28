"""受控修复服务的装配入口。"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .repair_loop import RepairLoop, RepairLoopConfig, RepairObserver
from .repair_executor import SoftwareTaskExecutor


def build_repair_loop(*, planner: Any, apply_patch: Any, run_tests: Any,
                      allowed_paths: tuple[str, ...], observer: RepairObserver | None = None,
                      max_attempts: int = 3) -> RepairLoop:
    """把模型 planner 与任务 Runner 装配成统一 RepairLoop。"""
    executor = SoftwareTaskExecutor(apply_patch, run_tests)
    return RepairLoop(planner=planner, executor=executor,
                      allowed_paths=allowed_paths,
                      config=RepairLoopConfig(max_attempts=max_attempts), observer=observer)


__all__ = ["build_repair_loop"]
