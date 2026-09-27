"""受控的软件任务补丁循环。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol

from react_agent.apps.patch_planner import parse_patch_plan


@dataclass(frozen=True)
class RepairLoopConfig:
    max_attempts: int = 3

    def __post_init__(self) -> None:
        if not isinstance(self.max_attempts, int) or self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")


class RepairObserver(Protocol):
    def emit(self, event: Mapping[str, Any], visibility: str) -> None: ...


_PLANNER_FAILURE_FIELDS = frozenset({"passed", "returncode", "failed_test", "stdout_tail", "stderr_tail", "changed_paths", "error"})


def _planner_safe_result(result: Mapping[str, Any]) -> dict[str, Any]:
    """只把约定的公开测试字段反馈给模型，避免泄露执行器内部数据。"""
    return {key: result[key] for key in _PLANNER_FAILURE_FIELDS if key in result}


@dataclass
class RepairLoop:
    """让 planner 生成补丁，并由外部 executor 负责应用和测试。"""

    planner: Callable[[Mapping[str, Any]], Mapping[str, Any]]
    executor: Callable[[tuple[Any, ...], bool], Mapping[str, Any]]
    allowed_paths: tuple[str, ...]
    config: RepairLoopConfig = field(default_factory=RepairLoopConfig)
    observer: RepairObserver | None = None

    def _emit(self, event: Mapping[str, Any], visibility: str) -> None:
        if self.observer is not None:
            self.observer.emit(event, visibility)

    def run(self, task_context: Mapping[str, Any]) -> dict[str, Any]:
        history: list[dict[str, Any]] = []
        feedback: dict[str, Any] = {"phase": "planning", **dict(task_context)}
        for attempt in range(1, self.config.max_attempts + 1):
            self._emit({"phase": "planning", "attempt": attempt}, "audit")
            try:
                raw_plan = self.planner(feedback)
                replacements = parse_patch_plan(raw_plan, allowed_paths=self.allowed_paths)
                self._emit({"phase": "patch_validated", "attempt": attempt,
                            "changed_paths": [item.path for item in replacements]}, "audit")
                public = dict(self.executor(replacements, False))
                record = {"attempt": attempt, "public_test": public}
                history.append(record)
                self._emit({"phase": "public_test", "attempt": attempt,
                            "status": "passed" if public.get("passed") is True else "failed",
                            "details": public}, "audit")
                if public.get("passed") is not True:
                    feedback = {**dict(task_context), "phase": "repair", "attempt": attempt,
                                "failure": _planner_safe_result(public)}
                    self._emit({"phase": "repair_feedback", "attempt": attempt,
                                "failure": feedback["failure"]}, "agent")
                    if attempt == self.config.max_attempts:
                        return {"status": "public_test_failed", "attempts": history}
                    continue
                hidden = dict(self.executor(replacements, True))
                record["hidden_test"] = hidden
                self._emit({"phase": "hidden_test", "attempt": attempt,
                            "status": "passed" if hidden.get("passed") is True else "failed",
                            "details": hidden}, "audit")
                if hidden.get("passed") is True:
                    return {"status": "succeeded", "attempts": history}
                return {"status": "hidden_test_failed", "attempts": history}
            except (TypeError, ValueError) as exc:
                history.append({"attempt": attempt, "error": str(exc)})
                feedback = {**dict(task_context), "phase": "repair", "attempt": attempt, "failure": {"error": str(exc)}}
        return {"status": "public_test_failed", "attempts": history}


__all__ = ["RepairLoop", "RepairLoopConfig"]
