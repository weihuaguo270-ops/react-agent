"""Core Workflow — declarative multi-step pipelines (self-built, no LangGraph).

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
    TOOL = "tool"          # call a registered tool function
    POLICY = "policy"      # pure Python policy / transform
    BRANCH = "branch"      # choose next steps via predicate (soft)
    FINAL = "final"        # mark completion


@dataclass
class Step:
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
    name: str
    description: str
    steps: list[Step]
    handlers: dict[str, Callable[..., Any]] = field(default_factory=dict)
    version: str = "1"


@dataclass
class StepRecord:
    step_id: str
    kind: str
    ok: bool
    started_at: float
    ended_at: float
    input: dict[str, Any] = field(default_factory=dict)
    output: Any = None
    error: str = ""


@dataclass
class WorkflowResult:
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
        """Export a Harness-compatible Format B-ish trajectory for cross-repo tooling."""
        traj_steps: list[dict[str, Any]] = []
        for i, s in enumerate(self.steps, start=1):
            traj_steps.append(
                {
                    "step": i,
                    "thought": f"workflow:{self.workflow}/{s.step_id}",
                    "action": s.kind,
                    "action_input": s.step_id,
                    "observation": (
                        s.error
                        if not s.ok
                        else (s.output if isinstance(s.output, str) else json.dumps(s.output, ensure_ascii=False)[:800])
                    ),
                }
            )
        return {
            "schema": "harness_trajectory_format_b",
            "run_id": self.run_id,
            "query": self.state.get("query", ""),
            "final_answer": self.answer,
            "ok": self.ok,
            "steps": traj_steps,
            "meta": {"workflow": self.workflow, "refused": self.refused},
        }


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
    def __init__(
        self,
        workflow: WorkflowDef,
        tool_registry: Optional[dict[str, Callable[..., Any]]] = None,
    ):
        self.workflow = workflow
        self.tool_registry = tool_registry or {}

    def run(self, initial_state: Optional[dict[str, Any]] = None) -> WorkflowResult:
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
                        result = fn(**kwargs)
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
