"""Built-in skills mapped to the work-assistant office scenarios."""
from __future__ import annotations

from typing import Any

from react_agent.skills.contracts import SkillDef
from react_agent.skills.business_boundaries import BusinessBoundary
from react_agent.skills.registry import register_skill


_DOCS_KEYWORDS = (
    "api", "auth", "authorization", "401", "403", "404", "429", "500",
    "502", "504", "trace", "日志", "报错", "错误码", "限流", "超时",
    "接口", "文档", "排障", "故障",
)
_EXPENSE_KEYWORDS = ("报销", "发票", "收据", "差旅", "费用", "额度", "审批")

_DOCS_INPUT_SCHEMA = {
    "type": "object",
    "required": ["query"],
    "properties": {
        "query": {"type": "string", "minLength": 1, "maxLength": 100_000},
        "error_response": {"type": ["object", "string", "null"]},
        "request_headers": {"type": ["object", "string", "null"]},
        "log_excerpt": {"type": ["string", "null"], "maxLength": 100_000},
        "trace_context": {"type": ["object", "string", "null"]},
        "run_health_check": {"type": "boolean"},
        "health_url": {"type": "string", "maxLength": 2_000},
        "multimodal_artifacts": {
            "type": "array", "maxItems": 10,
            "items": {
                "type": ["string", "object"],
                "properties": {
                    "path": {"type": "string", "minLength": 1},
                    "id": {"type": "string", "maxLength": 100},
                },
            },
        },
        "multimodal_max_bytes": {"type": "integer", "minimum": 1, "maximum": 200_000_000},
    },
}
_DOCS_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["ok", "answer", "refused", "citations", "diagnosis"],
    "properties": {
        "ok": {"type": "boolean"},
        "answer": {"type": "string"},
        "refused": {"type": "boolean"},
        "citations": {"type": "array"},
        "diagnosis": {"type": "object"},
        "multimodal": {"type": "object"},
    },
}
_EXPENSE_INPUT_SCHEMA = {
    "type": "object",
    "required": ["claim"],
    "properties": {
        "claim": {
            "type": "object",
            "required": ["category", "amount", "has_receipt"],
            "properties": {
                "category": {"type": "string", "minLength": 1},
                "amount": {"type": "number", "minimum": 0, "maximum": 100_000_000},
                "has_receipt": {"type": "boolean"},
                "pre_approved": {"type": "boolean"},
            },
        }
    },
}
_EXPENSE_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["ok", "answer", "refused", "decision", "citations"],
    "properties": {
        "ok": {"type": "boolean"},
        "answer": {"type": "string"},
        "refused": {"type": "boolean"},
        "decision": {"type": "string", "minLength": 1},
        "citations": {"type": "array", "minItems": 1},
    },
}


def _keyword_score(query: str, keywords: tuple[str, ...]) -> int:
    text = query.lower()
    return sum(2 for keyword in keywords if keyword.lower() in text)


def _match_docs(query: str, payload: dict[str, Any]) -> int:
    evidence = {"error_response", "log_excerpt", "trace_context", "request_headers"}
    return (80 if evidence.intersection(payload) else 0) + _keyword_score(query, _DOCS_KEYWORDS)


def _match_expense(query: str, payload: dict[str, Any]) -> int:
    structured = 100 if isinstance(payload.get("claim"), dict) else 0
    return structured + _keyword_score(query, _EXPENSE_KEYWORDS)


def _run_docs(payload: dict[str, Any]) -> dict[str, Any]:
    from react_agent.apps.docs_troubleshoot.tools import TOOL_REGISTRY as APP_TOOLS
    from react_agent.tools import TOOL_REGISTRY as CORE_TOOLS
    from react_agent.workflow import run_workflow

    result = run_workflow(
        "docs_troubleshoot",
        payload,
        tool_registry={**CORE_TOOLS, **APP_TOOLS},
    )
    output = result.to_dict()
    output.update(
        {
            "ok": result.ok,
            "policy": result.state.get("policy"),
            "done": bool(result.state.get("done")),
            "multimodal": result.state.get("multimodal_summary") or {},
        }
    )
    return output


def _verify_docs(output: dict[str, Any]) -> dict[str, bool]:
    return {
        "workflow_completed": bool(output.get("ok") and output.get("done")),
        "answer_policy_applied": bool(output.get("policy")),
        "citations_verified_or_refused": bool(
            output.get("refused") or output.get("citations")
        ),
        "diagnosis_built": isinstance(output.get("diagnosis"), dict)
        and bool(output["diagnosis"].get("phenomenon")),
    }


def _run_expense(payload: dict[str, Any]) -> dict[str, Any]:
    from react_agent.apps.expense.offline_answer import answer_offline

    return answer_offline({"claim": payload["claim"]})


def _verify_expense(output: dict[str, Any]) -> dict[str, bool]:
    return {
        "claim_parsed": bool(output.get("ok")),
        "deterministic_decision": bool(output.get("decision")),
        "policy_cited": bool(output.get("citations")),
    }


def _boundary(
    *, name: str, scenario: str, purpose: str, workflow: str,
    risk_level: str, agent_callable: bool, owner: str,
    allowed_tools: tuple[str, ...], required_steps: tuple[str, ...],
    required_inputs: tuple[str, ...], required_outputs: tuple[str, ...],
    success_conditions: tuple[str, ...], human_handoff_conditions: tuple[str, ...],
    forbidden_actions: tuple[str, ...],
) -> BusinessBoundary:
    return BusinessBoundary(
        name=name, version="1", scenario=scenario, purpose=purpose,
        workflow=workflow, risk_level=risk_level, agent_callable=agent_callable,
        owner=owner, allowed_tools=allowed_tools, required_steps=required_steps,
        required_inputs=required_inputs, required_outputs=required_outputs,
        success_conditions=success_conditions,
        human_handoff_conditions=human_handoff_conditions,
        forbidden_actions=forbidden_actions,
    )


def register_builtin_skills() -> None:
    register_skill(
        SkillDef(
            name="docs_troubleshoot",
            scenario="technical_support",
            description="Collect evidence, retrieve docs, enforce citations, and build a diagnosis.",
            version="1",
            workflow="docs_troubleshoot@5",
            risk_level="read_only",
            owner="support-platform",
            required_inputs=("query",),
            required_outputs=("answer", "refused", "citations", "diagnosis"),
            allowed_tools=(
                "parse_error_evidence",
                "parse_log_evidence",
                "parse_trace_context",
                "parse_request_headers",
                "search_docs",
                "lookup_api",
                "fetch_trace",
                "probe_service_health",
                "verify_citations",
            ),
            instructions=(
                "Parse available field evidence before retrieval.",
                "Retrieve runbook or API sources before stating facts.",
                "Build candidate causes and verification actions from evidence.",
                "Refuse when citation verification or evidence sufficiency fails.",
            ),
            release_checks=(
                "workflow_completed",
                "answer_policy_applied",
                "citations_verified_or_refused",
                "diagnosis_built",
            ),
            input_schema=_DOCS_INPUT_SCHEMA,
            output_schema=_DOCS_OUTPUT_SCHEMA,
            executor=_run_docs,
            verifier=_verify_docs,
            matcher=_match_docs,
            boundary=_boundary(
                name="docs_troubleshoot", scenario="technical_support",
                purpose="根据现场证据和文档生成可引用的排障结论，证据不足时拒答或升级。",
                workflow="docs_troubleshoot@5", risk_level="read_only", agent_callable=True,
                owner="support-platform", allowed_tools=(
                    "parse_error_evidence", "parse_log_evidence", "parse_trace_context",
                    "parse_request_headers", "search_docs", "lookup_api", "fetch_trace",
                    "probe_service_health", "verify_citations",
                ),
                required_steps=("解析现场证据", "检索 Runbook 或 API 文档", "验证引用", "生成根因候选和只读验证动作", "证据不足时拒答或升级"),
                required_inputs=("query",), required_outputs=("answer", "refused", "citations", "diagnosis"),
                success_conditions=("输出结构化 diagnosis", "引用真实存在或明确拒答", "不执行生产修复"),
                human_handoff_conditions=("证据不足以区分根因", "需要修改配置、重启或回滚", "访问未授权租户数据"),
                forbidden_actions=("modify_production", "restart_service", "rollback_production", "claim_unique_root_cause_without_evidence"),
            ),
        )
    )
    register_skill(
        SkillDef(
            name="expense_claim_review",
            scenario="expense_approval",
            description="Apply deterministic receipt, limit, and approval-level rules.",
            version="1",
            workflow="expense_rule_engine@1",
            risk_level="read_only",
            owner="finance-automation",
            required_inputs=("claim",),
            required_outputs=("answer", "refused", "decision", "citations"),
            allowed_tools=(),
            instructions=(
                "Require a structured claim with category, amount, and receipt state.",
                "Use the deterministic policy rule engine as the decision authority.",
                "Explain the decision code and cite the policy source.",
            ),
            release_checks=(
                "claim_parsed",
                "deterministic_decision",
                "policy_cited",
            ),
            input_schema=_EXPENSE_INPUT_SCHEMA,
            output_schema=_EXPENSE_OUTPUT_SCHEMA,
            executor=_run_expense,
            verifier=_verify_expense,
            matcher=_match_expense,
            boundary=_boundary(
                name="expense_claim_review", scenario="expense_approval",
                purpose="按确定性费用规则给出报销审核结果，不直接写入台账。",
                workflow="expense_rule_engine@1", risk_level="read_only", agent_callable=True,
                owner="finance-automation", allowed_tools=(),
                required_steps=("校验费用字段", "执行收据、额度和预审批规则", "返回决定代码和政策引用"),
                required_inputs=("claim",), required_outputs=("answer", "refused", "decision", "citations"),
                success_conditions=("决定来自规则引擎", "引用政策", "不修改 ExpenseLedger"),
                human_handoff_conditions=("规则未覆盖费用类型", "金额或凭证需要人工核验", "需要持久化审批结果"),
                forbidden_actions=("write_expense_ledger", "approve_without_receipt", "change_policy"),
            ),
        )
    )
