"""Registry, deterministic routing, and contract-checked skill execution."""
from __future__ import annotations

from typing import Any, Optional

from react_agent.skills.contracts import SkillDef, SkillPipelineResult, SkillResult, SkillRoute
from react_agent.skills.schema import SkillSchemaError, validate_schema


class SkillRoutingError(ValueError):
    """Raised when business intent cannot be routed without guessing."""


_REGISTRY: dict[str, SkillDef] = {}
_BUILTINS_LOADED = False


def register_skill(skill: SkillDef) -> None:
    if not skill.name.strip():
        raise ValueError("skill name is required")
    if skill.risk_level not in {"read_only", "business_write", "external_write"}:
        raise ValueError(f"unsupported skill risk level: {skill.risk_level}")
    if skill.status not in {"active", "deprecated", "experimental"}:
        raise ValueError(f"unsupported skill status: {skill.status}")
    if skill.status == "deprecated" and not skill.supersedes:
        raise ValueError("deprecated Skill must declare supersedes")
    _REGISTRY[skill.name] = skill


def _ensure_builtins() -> None:
    global _BUILTINS_LOADED
    if _BUILTINS_LOADED:
        return
    from react_agent.skills.builtins import register_builtin_skills

    register_builtin_skills()
    _BUILTINS_LOADED = True


def get_skill(name: str) -> SkillDef:
    _ensure_builtins()
    try:
        return _REGISTRY[name]
    except KeyError as exc:
        raise KeyError(f"unknown skill: {name}. available={sorted(_REGISTRY)}") from exc


def list_skills(
    *, agent_callable_only: bool = False, detail: str = "summary"
) -> list[dict[str, Any]]:
    _ensure_builtins()
    skills = sorted(_REGISTRY.values(), key=lambda item: item.name)
    if agent_callable_only:
        skills = [item for item in skills if item.agent_callable]
    return [item.context(detail) for item in skills]


def get_skill_context(name: str, *, level: str = "summary") -> dict[str, Any]:
    """Load one Skill context layer on demand (progressive disclosure)."""
    return get_skill(name).context(level)


def filter_tool_definitions(tool_defs: Optional[list[dict[str, Any]]], allowed_tools: set[str]) -> list[dict[str, Any]]:
    """Return only tool definitions allowed by the active Skill."""
    definitions = list(tool_defs or [])
    out: list[dict[str, Any]] = []
    for definition in definitions:
        name = ((definition.get("function") or {}).get("name"))
        if name in allowed_tools:
            out.append(definition)
    return out


def route_skill_decision(
    query: str = "", payload: Optional[dict[str, Any]] = None
) -> SkillRoute:
    """Return an auditable deterministic route; never asks an LLM to classify intent."""
    _ensure_builtins()
    state = dict(payload or {})
    explicit = str(state.get("skill") or state.get("app") or state.get("application") or "").strip()
    scored = []
    for skill in _REGISTRY.values():
        score = skill.matcher(query, state)
        if explicit and explicit in {skill.name, skill.scenario}:
            score += 1_000
        scored.append((score, skill.name, skill))
    candidates = [item for item in scored if item[0] > 0]
    if not candidates:
        raise SkillRoutingError("no business skill matched the request")
    candidates.sort(key=lambda item: (-item[0], item[1]))
    if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
        names = [item[1] for item in candidates if item[0] == candidates[0][0]]
        raise SkillRoutingError(f"ambiguous business skill route: {names}")
    top_score = candidates[0][0]
    second_score = candidates[1][0] if len(candidates) > 1 else 0
    if not explicit and top_score < 2:
        raise SkillRoutingError("business skill route confidence is below threshold")
    confidence = min(1.0, max(0.0, (top_score - second_score) / max(top_score, 1)))
    return SkillRoute(
        skill=candidates[0][1],
        score=top_score,
        confidence=confidence,
        candidates=tuple((item[1], item[0]) for item in candidates),
        reason="explicit selector" if explicit else "weighted business signals",
    )


def route_skill(query: str = "", payload: Optional[dict[str, Any]] = None) -> SkillDef:
    """Choose a skill with deterministic matchers; reject ties and low confidence."""
    return get_skill(route_skill_decision(query, payload).skill)


def run_skill(name: str, payload: Optional[dict[str, Any]] = None) -> SkillResult:
    """Run one explicit skill and verify its output contract."""
    skill = get_skill(name)
    if skill.status == "deprecated":
        return SkillResult(
            skill=skill.name,
            scenario=skill.scenario,
            workflow=skill.workflow,
            ok=False,
            checks={"lifecycle": False},
            error=f"skill {name} is deprecated; use {skill.supersedes}",
        )
    state = dict(payload or {})
    missing = [
        key for key in skill.required_inputs
        if key not in state or state[key] is None or state[key] == ""
    ]
    if missing:
        return SkillResult(
            skill=skill.name,
            scenario=skill.scenario,
            workflow=skill.workflow,
            ok=False,
            checks={"required_inputs": False},
            error=f"missing required inputs: {', '.join(missing)}",
        )

    try:
        if skill.input_schema:
            validate_schema(state, skill.input_schema)
    except SkillSchemaError as exc:
        return SkillResult(
            skill=skill.name,
            scenario=skill.scenario,
            workflow=skill.workflow,
            ok=False,
            checks={"input_schema": False},
            error=str(exc)[:500],
        )

    try:
        output = skill.executor(state)
        if not isinstance(output, dict):
            raise TypeError("skill executor must return a dict")
        if skill.output_schema:
            validate_schema(output, skill.output_schema)
        checks = {
            f"output:{key}": key in output and output[key] is not None
            for key in skill.required_outputs
        }
        checks.update(skill.verifier(output))
        return SkillResult(
            skill=skill.name,
            scenario=skill.scenario,
            workflow=skill.workflow,
            ok=all(checks.values()),
            output=output,
            checks=checks,
        )
    except SkillSchemaError as exc:
        return SkillResult(
            skill=skill.name,
            scenario=skill.scenario,
            workflow=skill.workflow,
            ok=False,
            checks={"output_schema": False},
            error=str(exc)[:500],
        )
    except Exception as exc:
        return SkillResult(
            skill=skill.name,
            scenario=skill.scenario,
            workflow=skill.workflow,
            ok=False,
            checks={"execution": False},
            error=str(exc)[:500],
        )


def route_and_run_skill(
    query: str = "", payload: Optional[dict[str, Any]] = None
) -> SkillResult:
    """Route first, then execute. Routing never delegates the choice to an LLM."""
    state = dict(payload or {})
    if query:
        state.setdefault("query", query)
    skill = route_skill(query=query, payload=state)
    return run_skill(skill.name, state)


def run_skill_pipeline(
    names: list[str] | tuple[str, ...], payload: Optional[dict[str, Any]] = None
) -> SkillPipelineResult:
    """Compose verified Skills in order, carrying prior outputs into later stages."""
    pipeline = tuple(names)
    if not pipeline:
        raise ValueError("Skill pipeline must contain at least one Skill")
    state = dict(payload or {})
    results: list[SkillResult] = []
    for name in pipeline:
        result = run_skill(name, state)
        results.append(result)
        if not result.ok:
            return SkillPipelineResult(
                pipeline=pipeline,
                ok=False,
                results=results,
                output=state,
                failed_at=name,
            )
        state.update(result.output)
        state.setdefault("skill_outputs", {})[name] = dict(result.output)
    return SkillPipelineResult(pipeline=pipeline, ok=True, results=results, output=state)
