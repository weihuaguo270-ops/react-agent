"""Agent-callable discovery and execution tools for low-risk business skills."""
from __future__ import annotations

import json
from typing import Any

from react_agent.skills.registry import (
    get_skill,
    get_skill_context,
    list_skills,
    run_skill,
)


def list_business_skills_tool() -> str:
    """List only skills that are safe to expose to the model runtime."""
    return json.dumps(
        {"skills": list_skills(agent_callable_only=True, detail="summary")},
        ensure_ascii=False,
    )


def get_business_skill_context_tool(name: str, level: str = "instructions") -> str:
    """Progressively load one Skill's instructions or full contract."""
    try:
        skill = get_skill(name)
        if not skill.agent_callable:
            return json.dumps(
                {"ok": False, "error": "skill requires an explicit controlled caller"},
                ensure_ascii=False,
            )
        return json.dumps(
            {"ok": True, "context": get_skill_context(name, level=level)},
            ensure_ascii=False,
        )
    except (KeyError, ValueError) as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)


def run_business_skill_tool(
    name: str,
    query: str = "",
    payload_json: str = "",
) -> str:
    """Run an explicitly named low-risk skill through its output verifier."""
    try:
        skill = get_skill(name)
    except KeyError as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
    if not skill.agent_callable:
        return json.dumps(
            {
                "ok": False,
                "error": f"skill {name} requires an explicit controlled caller",
                "risk_level": skill.risk_level,
            },
            ensure_ascii=False,
        )

    payload: dict[str, Any] = {}
    if payload_json.strip():
        try:
            decoded = json.loads(payload_json)
        except json.JSONDecodeError as exc:
            return json.dumps(
                {"ok": False, "error": f"invalid payload_json: {exc}"},
                ensure_ascii=False,
            )
        if not isinstance(decoded, dict):
            return json.dumps(
                {"ok": False, "error": "payload_json must decode to an object"},
                ensure_ascii=False,
            )
        payload.update(decoded)
    if query:
        payload.setdefault("query", query)
    return json.dumps(run_skill(name, payload).to_dict(), ensure_ascii=False)


LIST_BUSINESS_SKILLS_DEF = {
    "type": "function",
    "function": {
        "name": "list_business_skills",
        "description": "列出可由 Agent 调用的只读业务 Skill 及其输入、工具和输出契约。",
        "parameters": {"type": "object", "properties": {}},
    },
}

RUN_BUSINESS_SKILL_DEF = {
    "type": "function",
    "function": {
        "name": "run_business_skill",
        "description": (
            "运行显式命名的只读业务 Skill，并执行 Workflow/Policy 和输出验证。"
            "外部写入 Skill 不允许通过此工具启动。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "enum": ["docs_troubleshoot", "expense_claim_review"],
                    "description": "业务 Skill 名称",
                },
                "query": {"type": "string", "description": "自然语言业务问题"},
                "payload_json": {
                    "type": "string",
                    "description": "结构化输入 JSON；报销 Skill 需包含 claim 对象",
                },
            },
            "required": ["name"],
        },
    },
}

GET_BUSINESS_SKILL_CONTEXT_DEF = {
    "type": "function",
    "function": {
        "name": "get_business_skill_context",
        "description": "按需加载一个业务 Skill 的下一层指令或完整契约，避免一次性注入所有上下文。",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "enum": ["docs_troubleshoot", "expense_claim_review"]},
                "level": {"type": "string", "enum": ["instructions", "full"]},
            },
            "required": ["name"],
        },
    },
}

SKILL_TOOL_DEFINITIONS = [
    LIST_BUSINESS_SKILLS_DEF,
    GET_BUSINESS_SKILL_CONTEXT_DEF,
    RUN_BUSINESS_SKILL_DEF,
]
SKILL_TOOL_REGISTRY = {
    "list_business_skills": list_business_skills_tool,
    "get_business_skill_context": get_business_skill_context_tool,
    "run_business_skill": run_business_skill_tool,
}
