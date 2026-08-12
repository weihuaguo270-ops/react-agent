"""Offline docs_troubleshoot Agent loop — tool selection + Harness trajectory.

Default runtime for the main scenario: observation-driven tool calls (ReAct-shaped),
not a fixed DAG. Workflow remains available via REACT_AGENT_DOCS_ENGINE=workflow.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from react_agent.apps.docs_troubleshoot.draft import build_draft_from_hits
from react_agent.apps.docs_troubleshoot.evidence import collect_evidence_bundle
from react_agent.apps.docs_troubleshoot.policy import should_refuse_query
from react_agent.apps.docs_troubleshoot.prompt import get_system_prompt
from react_agent.harness import current_trajectory, finish_trajectory, start_trajectory
from react_agent.harness.tool_boundary import execute_registered_tool
from react_agent.tools import TOOL_REGISTRY, enable_app_tools


def docs_engine() -> str:
    """agent (default) | workflow"""
    return os.environ.get("REACT_AGENT_DOCS_ENGINE", "agent").strip().lower() or "agent"


@dataclass
class AgentRunResult:
    ok: bool
    answer: str
    refused: bool
    citations: list[dict[str, Any]] = field(default_factory=list)
    diagnosis: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)
    trajectory_id: str = ""
    agent_steps: list[dict[str, Any]] = field(default_factory=list)

    def to_workflow_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "answer": self.answer,
            "refused": self.refused,
            "citations": self.citations,
            "diagnosis": self.diagnosis,
            "trajectory_id": self.trajectory_id,
            "engine": "agent",
            "agent_steps": self.agent_steps,
        }


_API_NEEDLE = re.compile(
    r"api|auth|authorization|bearer|401|403|404|429|500|502|504|endpoint|webhook|"
    r"鉴权|接口|错误码|限流|超时",
    re.I,
)


def _run_tool(name: str, args: dict[str, Any]) -> str:
    try:
        out = execute_registered_tool(name, args, TOOL_REGISTRY)
        return out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)[:300]}, ensure_ascii=False)


def _record_step(
    step: int,
    thought: str,
    action: str,
    args: dict[str, Any],
    observation: str,
) -> None:
    traj = current_trajectory()
    if not traj:
        return
    traj.start_step(step)
    traj.add_step(
        step,
        thought=thought,
        action_name=action,
        action_args=json.dumps(args, ensure_ascii=False)[:800],
        observation=observation[:2000],
    )


def _trace_id_from_state(state: dict[str, Any]) -> str:
    bundle = state.get("evidence_bundle") or {}
    for item in bundle.get("items") or []:
        tid = str(item.get("trace_id") or "").strip()
        if tid:
            return tid
    m = re.search(r"trace_id[=:\s]+([a-zA-Z0-9_-]+)", str(state.get("log_excerpt") or ""))
    return m.group(1) if m else ""


def _should_lookup_api(state: dict[str, Any]) -> bool:
    query = str(state.get("query") or "")
    if _API_NEEDLE.search(query):
        return True
    if state.get("error_response"):
        return True
    bundle = state.get("evidence_bundle") or {}
    for item in bundle.get("items") or []:
        if item.get("type") in ("http_error", "error_response"):
            return True
    return False


def _merge_search(state: dict[str, Any], key: str, observation: str) -> None:
    try:
        parsed = json.loads(observation)
    except json.JSONDecodeError:
        state[key] = {"ok": False, "results": []}
        return
    state[key] = parsed


def decide_next_tool(state: dict[str, Any], called: set[str]) -> Optional[tuple[str, str, dict[str, Any]]]:
    """Observation-driven next action: (thought, tool_name, args)."""
    query = str(state.get("query") or "")

    if state.get("error_response") and "parse_error_evidence" not in called:
        err = state["error_response"]
        status = 0
        body = ""
        if isinstance(err, dict):
            status = int(err.get("status") or err.get("status_code") or 0)
            body = json.dumps(err.get("error") or err, ensure_ascii=False)
        else:
            body = str(err)
        return (
            "Parse HTTP error JSON into structured field evidence before retrieval.",
            "parse_error_evidence",
            {"status_code": status, "body_json": body},
        )

    if state.get("log_excerpt") and "parse_log_evidence" not in called:
        return (
            "Extract trace_id and error lines from the log excerpt.",
            "parse_log_evidence",
            {"log_text": str(state.get("log_excerpt") or "")},
        )

    if state.get("trace_context") and "parse_trace_context" not in called:
        ctx = state["trace_context"]
        raw = ctx if isinstance(ctx, str) else json.dumps(ctx, ensure_ascii=False)
        return (
            "Normalize distributed trace JSON for ranking and diagnosis.",
            "parse_trace_context",
            {"trace_json": raw},
        )

    if state.get("request_headers") and "parse_request_headers" not in called:
        hdr = state["request_headers"]
        raw = hdr if isinstance(hdr, str) else json.dumps(hdr, ensure_ascii=False)
        return (
            "Redact and parse request headers as optional evidence.",
            "parse_request_headers",
            {"headers_json": raw},
        )

    if "search_docs" not in called:
        return (
            "Retrieve internal runbook/docs before stating any fact.",
            "search_docs",
            {"query": query, "top_k": 3},
        )

    if _should_lookup_api(state) and "lookup_api" not in called:
        return (
            "API/auth/error context detected — supplement with API reference retrieval.",
            "lookup_api",
            {"topic": query, "top_k": 2},
        )

    tid = _trace_id_from_state(state)
    if tid and "fetch_trace" not in called:
        return (
            f"trace_id {tid} present — fetch trace bundle for span-level evidence.",
            "fetch_trace",
            {"trace_id": tid},
        )

    if state.get("run_health_check") and "probe_service_health" not in called:
        url = str(state.get("health_url") or "")
        return (
            "Run read-only health probe as a verify action.",
            "probe_service_health",
            {"url": url} if url else {},
        )

    return None


def run_docs_agent(initial: Optional[dict[str, Any]] = None) -> AgentRunResult:
    """Offline Agent loop: tool calls → draft → verify_citations → policy → diagnosis."""
    os.environ.setdefault("REACT_AGENT_APP", "docs_troubleshoot")
    os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")
    enable_app_tools()

    state: dict[str, Any] = dict(initial or {})
    query = str(state.get("query") or "").strip()
    if not query:
        return AgentRunResult(ok=False, answer="query is required", refused=True, state=state)

    start_trajectory(query, "offline-agent", get_system_prompt(query))
    called: set[str] = set()
    agent_steps: list[dict[str, Any]] = []
    step_num = 0
    max_tool_steps = int(os.environ.get("REACT_AGENT_DOCS_AGENT_MAX_STEPS", "12"))

    if should_refuse_query(query):
        state["need_refuse"] = True
        state["draft"] = "依据不足，无法给出确定结论。"
        state["allowed_sources"] = []
    else:
        state["evidence_bundle"] = collect_evidence_bundle(state)
        while step_num < max_tool_steps:
            nxt = decide_next_tool(state, called)
            if nxt is None:
                break
            thought, tool, args = nxt
            step_num += 1
            obs = _run_tool(tool, args)
            called.add(tool)
            _record_step(step_num, thought, tool, args, obs)
            agent_steps.append(
                {"step": step_num, "thought": thought, "action": tool, "args": args}
            )

            if tool == "search_docs":
                _merge_search(state, "search_hits", obs)
            elif tool == "lookup_api":
                _merge_search(state, "api_hits", obs)
            elif tool.startswith("parse_") or tool == "fetch_trace":
                state["evidence_bundle"] = collect_evidence_bundle(state)
            elif tool == "probe_service_health":
                try:
                    state["health_probe"] = json.loads(obs)
                except json.JSONDecodeError:
                    state["health_probe"] = obs

        draft_out = build_draft_from_hits(
            query,
            state.get("search_hits"),
            state.get("api_hits"),
            evidence_bundle=state.get("evidence_bundle"),
        )
        state.update(draft_out)

        # Agent must verify citations before release (same contract as LLM react_loop prompt).
        step_num += 1
        draft = str(state.get("draft") or "")
        allowed = ",".join(state.get("allowed_sources") or [])
        verify_obs = _run_tool(
            "verify_citations",
            {"answer": draft, "allowed_sources": allowed},
        )
        _record_step(
            step_num,
            "Verify draft cites corpus sources; refuse if verification fails.",
            "verify_citations",
            {"answer": draft[:200], "allowed_sources": allowed[:120]},
            verify_obs,
        )
        agent_steps.append(
            {
                "step": step_num,
                "thought": "citation verification gate",
                "action": "verify_citations",
            }
        )
        try:
            check = json.loads(verify_obs)
        except json.JSONDecodeError:
            check = {"ok": False}
        if not check.get("ok") and not state.get("need_refuse"):
            state["need_refuse"] = True
            if "依据不足" not in draft:
                state["draft"] = (
                    "依据不足，无法给出确定结论。"
                    "请补充报错原文、相关配置，或先检索文档后再答。"
                )

    from react_agent.apps.docs_troubleshoot.policy import enforce_answer_policy
    from react_agent.apps.docs_troubleshoot.diagnosis import build_diagnosis
    from react_agent.apps.docs_troubleshoot.draft import as_results

    policy_out = enforce_answer_policy(
        str(state.get("draft") or ""),
        allowed_sources=state.get("allowed_sources") or None,
        must_refuse=bool(state.get("need_refuse")),
    )
    state["answer"] = policy_out["answer"]
    state["refused"] = policy_out.get("refused", False)
    state["citations"] = policy_out.get("citations") or []
    state["policy"] = policy_out.get("policy")

    hits = as_results(state.get("search_hits")) + as_results(state.get("api_hits"))
    diagnosis = build_diagnosis(
        query=query,
        evidence_bundle=state.get("evidence_bundle") or {},
        draft=str(state.get("answer") or ""),
        ranked_sources=list(state.get("ranked_sources") or []),
        refused=bool(state.get("refused")),
        retrieval_hits=hits,
    )

    traj = current_trajectory()
    trajectory_id = traj.session_id if traj else ""
    finish_trajectory(str(state.get("answer") or ""))

    return AgentRunResult(
        ok=True,
        answer=str(state.get("answer") or ""),
        refused=bool(state.get("refused")),
        citations=list(state.get("citations") or []),
        diagnosis=diagnosis,
        state=state,
        trajectory_id=trajectory_id,
        agent_steps=agent_steps,
    )


def run_docs(initial: Optional[dict[str, Any]] = None) -> AgentRunResult:
    """Dispatch: agent (default) or legacy workflow."""
    if docs_engine() == "workflow":
        from react_agent.workflow import run_workflow

        initial = dict(initial or {})
        result = run_workflow("docs_troubleshoot", initial)
        return AgentRunResult(
            ok=bool(result.ok),
            answer=result.answer,
            refused=bool(result.refused),
            citations=list(result.citations or []),
            diagnosis=dict(result.diagnosis or {}),
            state=dict(result.state),
            trajectory_id=result.run_id,
            agent_steps=[
                {"step": i + 1, "action": s.step_id, "kind": s.kind}
                for i, s in enumerate(result.steps)
            ],
        )
    return run_docs_agent(initial)
