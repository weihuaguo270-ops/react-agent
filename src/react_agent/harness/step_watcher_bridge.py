"""StepWatcher 桥接 — 可选依赖 trace-debugger，执行中检测并记录失败。

环境变量：
  REACT_AGENT_STEP_WATCHER=1   启用（默认开；设 0/false 关闭）
  REACT_AGENT_FAILURE_LOG      JSONL 路径（默认 src/react_agent/.tdebug/failures.jsonl）
"""
from __future__ import annotations

import os
import time
from typing import Any, Optional

from .recorder import TRAJECTORY_DIR


def step_watcher_enabled() -> bool:
    val = os.environ.get("REACT_AGENT_STEP_WATCHER", "1").strip().lower()
    return val not in ("0", "false", "off", "no")


def default_failure_log_path() -> str:
    custom = os.environ.get("REACT_AGENT_FAILURE_LOG", "").strip()
    if custom:
        return custom
    base = os.path.dirname(TRAJECTORY_DIR)
    return os.path.join(base, ".tdebug", "failures.jsonl")


def create_watcher(
    session_id: str,
    query: str,
    model: str,
) -> Optional[Any]:
    if not step_watcher_enabled():
        return None
    try:
        from trace_debugger.runtime import StepWatcher
    except ImportError:
        return None

    source_file = os.path.join(TRAJECTORY_DIR, f"traj_{session_id}.json")
    return StepWatcher(
        session_id=session_id,
        query=query,
        model=model,
        record_path=default_failure_log_path(),
        source_file=source_file,
    )


def _entry_to_step_kwargs(entry: dict) -> dict[str, Any]:
    action = entry.get("action") or {}
    if not action and entry.get("actions"):
        acts = entry.get("actions") or []
        action = acts[-1] if acts else {}
    if not isinstance(action, dict):
        action = {}
    return {
        "step_index": entry["step"],
        "thought": entry.get("thought", ""),
        "action_name": action.get("name", ""),
        "action_args": action.get("arguments", ""),
        "observation": entry.get("observation", ""),
        "duration": float(entry.get("duration_seconds") or 0.0),
        "tokens": int(entry.get("tokens_estimated") or 0),
    }


def notify_step(watcher: Any, entry: dict, *, live_print: bool = True) -> None:
    """对单步做实时检测，并将 failure_tags 写回 entry。"""
    from trace_debugger.record import format_event_readable
    from trace_debugger.runtime import failure_tags_from_step

    kwargs = _entry_to_step_kwargs(entry)
    sa = watcher.on_step(**kwargs)
    tags = failure_tags_from_step(
        sa,
        thought=kwargs.get("thought", ""),
        action_args=kwargs.get("action_args", ""),
        observation=kwargs.get("observation", ""),
    )
    if tags:
        entry.update(tags)
    if live_print and not sa.success and sa.failure_type:
        ev = {
            "recorded_at": "",
            "session_id": watcher.session_id,
            "query": watcher.query,
            "failure_type": sa.failure_type,
            "failure_detail": sa.failure_detail,
            "suggestion": sa.suggestion,
            "step_index": sa.step_index,
            "action": sa.action,
            "action_args": kwargs.get("action_args", ""),
            "thought": kwargs.get("thought", ""),
            "observation": kwargs.get("observation", ""),
            "duration_seconds": sa.duration,
        }
        from trace_debugger.record import enrich_failure_event
        print(format_event_readable(enrich_failure_event(ev)))


_MERGE_KEYS = (
    "failure_tags", "failure_label", "failure_summary", "failure_detail",
    "failure_severity", "failure_context", "failure", "suggestion",
)


def _merge_watched_steps(traj: Any, watched: dict) -> None:
    by_step = {s["step"]: s for s in watched.get("steps", [])}
    for entry in traj.steps:
        ws = by_step.get(entry["step"])
        if not ws:
            continue
        for key in _MERGE_KEYS:
            if key in ws:
                entry[key] = ws[key]


def finalize_watcher(watcher: Any, traj: Any) -> None:
    """任务结束：路径级检测 + 合并 failure_tags + 提示摘要路径。"""
    duration = round(time.time() - traj._start_time, 2)
    watcher.on_finish(
        final_answer=traj.final_answer,
        total_duration=duration,
        metadata={"total_tokens_estimated": traj.total_tokens_estimated},
    )
    _merge_watched_steps(traj, watcher.to_trajectory_dict())
    try:
        from trace_debugger.record import load_failure_events, session_summary_path
        events = load_failure_events(watcher.record_path, session_id=traj.session_id)
        if events:
            summary = session_summary_path(watcher.record_path, traj.session_id)
            if summary.is_file():
                print(f"  [StepWatcher] 失败复盘摘要 -> {summary}")
    except Exception:
        pass


def merge_failure_tags(traj: Any, watcher: Any) -> None:
    """将 watcher 中的 failure 字段合并到 traj.steps。"""
    _merge_watched_steps(traj, watcher.to_trajectory_dict())
