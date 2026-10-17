"""Core Workflow — declarative multi-step pipelines (self-built).

Inspired by patterns in production agent stacks (deterministic Flows / skills):
fixed steps, shared state, tool/policy nodes, auditable run records.

Usage:
    from react_agent.workflow import get_workflow, run_workflow
    result = run_workflow("docs_troubleshoot", {"query": "401 怎么排查？"})
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional


class StepKind(str, Enum):
    """工作流步骤的执行语义。"""

    TOOL = "tool"          # call a registered tool function
    POLICY = "policy"      # pure Python policy / transform
    BRANCH = "branch"      # choose next steps via predicate (soft)
    FINAL = "final"        # mark completion


@dataclass
class Step:
    """声明式步骤及其依赖、参数映射和失败策略。"""

    id: str
    kind: StepKind
    description: str = ""
    tool: str = ""
    # Map workflow state keys → tool kwargs; values starting with "$" read from state
    args: dict[str, Any] = field(default_factory=dict)
    # Where to store tool/policy output in state
    output_key: str = "last"
    depends_on: list[str] = field(default_factory=list)
    # POLICY / BRANCH callable name registered on the workflow
    handler: str = ""
    # If True, failure stops the workflow
    critical: bool = True
    # Soft skip: state key (no $) or "$key"; falsy → skip step (CrewAI-router-inspired)
    when: str = ""


@dataclass
class WorkflowDef:
    """带版本和处理器注册表的完整工作流定义。"""

    name: str
    description: str
    steps: list[Step]
    handlers: dict[str, Callable[..., Any]] = field(default_factory=dict)
    version: str = "1"


@dataclass
class StepRecord:
    """单个步骤的输入、结果、耗时和错误证据。"""

    step_id: str
    kind: str
    ok: bool
    started_at: float
    ended_at: float
    input: dict[str, Any] = field(default_factory=dict)
    output: Any = None
    error: str = ""
    tool_name: str = ""


@dataclass
class WorkflowResult:
    """一次工作流执行的状态和可审计步骤记录。"""

    workflow: str
    run_id: str
    ok: bool
    state: dict[str, Any]
    steps: list[StepRecord]
    answer: str = ""
    refused: bool = False
    citations: list[dict[str, Any]] = field(default_factory=list)
    diagnosis: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """生成面向报告的摘要，不展开完整共享状态。"""
        return {
            "workflow": self.workflow,
            "run_id": self.run_id,
            "ok": self.ok,
            "answer": self.answer,
            "refused": self.refused,
            "citations": self.citations,
            "diagnosis": self.diagnosis,
            "state_keys": sorted(self.state.keys()),
            "steps": [
                {
                    "step_id": s.step_id,
                    "kind": s.kind,
                    "ok": s.ok,
                    "error": s.error,
                    "duration_ms": int((s.ended_at - s.started_at) * 1000),
                }
                for s in self.steps
            ],
        }

    def to_trajectory(self) -> dict[str, Any]:
        """Export the canonical Harness Format B trajectory.

        Workflow records use the same wire fields as ReAct Recorder.  The
        previous ``run_id/schema/action_input`` shape was only Format B-ish
        and could not be consumed by the shared schema without an adapter.
        """
        from react_agent.harness.contracts import StopReason, serialize_trajectory

        traj_steps: list[dict[str, Any]] = []
        for i, s in enumerate(self.steps, start=1):
            observation = (
                s.error
                if not s.ok
                else (
                    s.output
                    if isinstance(s.output, str)
                    else json.dumps(s.output, ensure_ascii=False)[:800]
                )
            )
            traj_steps.append(
                {
                    "step": i,
                    "thought": f"workflow:{self.workflow}/{s.step_id}",
                    "action": {
                        "name": s.tool_name or f"workflow.{s.kind}",
                        "arguments": json.dumps(
                            s.input if s.tool_name else {"step_id": s.step_id},
                            ensure_ascii=False,
                        ),
                    },
                    "observation": str(observation),
                    "duration_seconds": round(s.ended_at - s.started_at, 3),
                }
            )
        stop_reason = StopReason.COMPLETED.value
        error_code = ""
        if self.refused:
            stop_reason = StopReason.POLICY_DENIED.value
        elif not self.ok:
            stop_reason = StopReason.TOOL_ERROR.value
            for record in reversed(self.steps):
                if record.ok or not record.error:
                    continue
                try:
                    error_payload = json.loads(record.error)
                except (TypeError, json.JSONDecodeError):
                    error_payload = {}
                if isinstance(error_payload, dict):
                    error_code = str(error_payload.get("error_code") or "")
                    candidate = str(error_payload.get("stop_reason") or "")
                    if candidate in {reason.value for reason in StopReason}:
                        stop_reason = candidate
                break
        trajectory = serialize_trajectory(
            session_id=self.run_id,
            query=str(self.state.get("query", "")),
            final_answer=self.answer,
            steps=traj_steps,
            metadata={
                "workflow": self.workflow,
                "execution_mode": "workflow",
                "ok": self.ok,
                "refused": self.refused,
                "stop_reason": stop_reason,
                **({"error_code": error_code} if error_code else {}),
            },
        )
        trajectory.update({
            # Compatibility marker for consumers that predate the formal
            # session_id/schema_version fields. New consumers must validate
            # the complete Format B object.
            "schema": "harness_trajectory_format_b",
            "ok": self.ok,
        })
        return trajectory


def _resolve_args(args: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in (args or {}).items():
        if isinstance(v, str) and v.startswith("$"):
            out[k] = state.get(v[1:])
        else:
            out[k] = v
    return out


def _topo_levels(steps: list[Step]) -> list[list[Step]]:
    by_id = {s.id: s for s in steps}
    remaining = set(by_id)
    done: set[str] = set()
    levels: list[list[Step]] = []
    while remaining:
        ready = [
            by_id[i]
            for i in list(remaining)
            if all(d in done for d in by_id[i].depends_on)
        ]
        if not ready:
            raise RuntimeError(f"workflow cycle or missing deps: {sorted(remaining)}")
        levels.append(sorted(ready, key=lambda s: s.id))
        for s in ready:
            remaining.remove(s.id)
            done.add(s.id)
    return levels


def validate_workflow(workflow: WorkflowDef) -> None:
    """Fail fast on duplicate ids, missing deps, or cycles (register-time)."""
    ids = [s.id for s in workflow.steps]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate step ids in workflow {workflow.name}")
    known = set(ids)
    for s in workflow.steps:
        for d in s.depends_on:
            if d not in known:
                raise ValueError(f"step {s.id} depends on unknown {d}")
        if s.kind == StepKind.TOOL and not s.tool:
            raise ValueError(f"tool step {s.id} missing tool=")
        if s.kind in (StepKind.POLICY, StepKind.FINAL, StepKind.BRANCH) and not s.handler:
            raise ValueError(f"handler step {s.id} missing handler=")
        if s.handler and s.handler not in workflow.handlers:
            raise ValueError(f"step {s.id} handler {s.handler!r} not registered")
    _topo_levels(workflow.steps)


def _when_ok(when: str, state: dict[str, Any]) -> bool:
    if not when:
        return True
    key = when[1:] if when.startswith("$") else when
    return bool(state.get(key))


class WorkflowRunner:
    """按拓扑层级确定性执行工作流。

    同一层仍顺序执行，以避免共享状态写入竞态。关键步骤失败立即返回，
    非关键步骤失败会保留记录并继续后续步骤。
    """

    def __init__(
        self,
        workflow: WorkflowDef,
        tool_registry: Optional[dict[str, Callable[..., Any]]] = None,
    ):
        self.workflow = workflow
        self.tool_registry = tool_registry or {}

    def run(self, initial_state: Optional[dict[str, Any]] = None) -> WorkflowResult:
        """复制初始状态并执行一次工作流，返回独立运行证据。"""
        state: dict[str, Any] = dict(initial_state or {})
        run_id = f"wf-{uuid.uuid4().hex[:12]}"
        records: list[StepRecord] = []
        ok = True

        for level in _topo_levels(self.workflow.steps):
            # Sequential within level for predictable state writes (parallel later)
            for step in level:
                t0 = time.time()
                if not _when_ok(step.when, state):
                    records.append(
                        StepRecord(
                            step_id=step.id,
                            kind=step.kind.value,
                            ok=True,
                            started_at=t0,
                            ended_at=time.time(),
                            output={"skipped": True, "when": step.when},
                        )
                    )
                    continue
                rec = StepRecord(
                    step_id=step.id,
                    kind=step.kind.value,
                    ok=True,
                    started_at=t0,
                    ended_at=t0,
                )
                try:
                    if step.kind == StepKind.TOOL:
                        fn = self.tool_registry.get(step.tool)
                        if fn is None:
                            raise KeyError(f"tool not found: {step.tool}")
                        kwargs = _resolve_args(step.args, state)
                        rec.input = kwargs
                        rec.tool_name = step.tool
                        from react_agent.harness.tool_boundary import (
                            execute_registered_tool,
                        )

                        result = execute_registered_tool(
                            step.tool,
                            kwargs,
                            self.tool_registry,
                            source="workflow",
                        )
                        # Tools often return JSON strings
                        if isinstance(result, str):
                            try:
                                parsed = json.loads(result)
                            except json.JSONDecodeError:
                                parsed = result
                        else:
                            parsed = result
                        state[step.output_key] = parsed
                        rec.output = parsed if not isinstance(parsed, str) else parsed[:500]
                    elif step.kind in (StepKind.POLICY, StepKind.FINAL, StepKind.BRANCH):
                        handler = self.workflow.handlers.get(step.handler)
                        if handler is None:
                            raise KeyError(f"handler not found: {step.handler}")
                        kwargs = _resolve_args(step.args, state)
                        rec.input = {k: (str(v)[:120] if not isinstance(v, (dict, list)) else v) for k, v in kwargs.items()}
                        result = handler(state, **kwargs) if kwargs else handler(state)
                        if isinstance(result, dict):
                            state.update(result)
                        elif result is not None:
                            state[step.output_key] = result
                        rec.output = result if not isinstance(result, dict) else {
                            k: result[k] for k in list(result)[:8]
                        }
                    else:
                        raise ValueError(f"unknown step kind: {step.kind}")
                except Exception as e:
                    rec.ok = False
                    from react_agent.harness.contracts import tool_error_from_exception

                    if step.kind == StepKind.TOOL:
                        rec.error = json.dumps(
                            tool_error_from_exception(
                                e, source="workflow", tool_name=step.tool
                            ),
                            ensure_ascii=False,
                        )[:800]
                    else:
                        rec.error = str(e)[:400]
                    if step.critical:
                        ok = False
                        rec.ended_at = time.time()
                        records.append(rec)
                        return WorkflowResult(
                            workflow=self.workflow.name,
                            run_id=run_id,
                            ok=False,
                            state=state,
                            steps=records,
                            answer=str(state.get("answer") or state.get("error") or rec.error),
                            refused=bool(state.get("refused")),
                            citations=list(state.get("citations") or []),
                            diagnosis=dict(state.get("diagnosis") or {}),
                        )
                rec.ended_at = time.time()
                records.append(rec)

        return WorkflowResult(
            workflow=self.workflow.name,
            run_id=run_id,
            ok=ok,
            state=state,
            steps=records,
            answer=str(state.get("answer") or ""),
            refused=bool(state.get("refused")),
            citations=list(state.get("citations") or []),
            diagnosis=dict(state.get("diagnosis") or {}),
        )
