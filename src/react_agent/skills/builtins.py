"""Built-in skills mapped to the repository's three business scenarios."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from react_agent.skills.contracts import SkillDef
from react_agent.skills.registry import register_skill


_DOCS_KEYWORDS = (
    "api", "auth", "authorization", "401", "403", "404", "429", "500",
    "502", "504", "trace", "日志", "报错", "错误码", "限流", "超时",
    "接口", "文档", "排障", "故障",
)
_EXPENSE_KEYWORDS = ("报销", "发票", "收据", "差旅", "费用", "额度", "审批")
_GITHUB_KEYWORDS = ("github", "issue", "pull request", "draft pr", "代码交付")
_SECURITY_KEYWORDS = ("cve", "kev", "ioc", "att&ck", "威胁情报", "安全研判", "漏洞研判", "threatfox")

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
_GITHUB_INPUT_SCHEMA = {
    "type": "object",
    "required": [
        "task_id", "repository", "issue_url", "replacements", "test_command",
        "acceptance_criteria", "artifact_dir", "idempotency_key",
    ],
    "properties": {
        "task_id": {"type": "string", "minLength": 1, "maxLength": 200},
        "repository": {"type": "string", "minLength": 1},
        "issue_url": {"type": "string", "minLength": 1},
        "split": {"type": "string", "enum": ["dev", "golden", "held_out", "production"]},
        "replacements": {
            "type": "array", "minItems": 1,
            "items": {
                "type": "object", "required": ["path", "old", "new"],
                "properties": {
                    "path": {"type": "string", "minLength": 1},
                    "old": {"type": "string", "minLength": 1},
                    "new": {"type": "string"},
                },
            },
        },
        "test_command": {"type": "array", "minItems": 2, "items": {"type": "string", "minLength": 1}},
        "acceptance_criteria": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}},
        "artifact_dir": {"type": "string", "minLength": 1},
        "idempotency_key": {"type": "string", "minLength": 1, "maxLength": 300},
        "mode": {"type": "string", "enum": ["shadow", "guarded"]},
        "publish_draft_pr": {"type": "boolean"},
    },
}
_GITHUB_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["status", "plan_sha256", "metrics", "episode"],
    "properties": {
        "status": {"type": "string", "minLength": 1},
        "plan_sha256": {"type": "string", "minLength": 1},
        "metrics": {"type": "object"},
        "episode": {"type": "object"},
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


def _match_github(query: str, payload: dict[str, Any]) -> int:
    markers = {"repository", "replacements", "test_command", "acceptance_criteria"}
    structured = 120 if markers.issubset(payload) else 0
    return structured + _keyword_score(query, _GITHUB_KEYWORDS)


def _match_security(query: str, payload: dict[str, Any]) -> int:
    structured = 100 if any(key in payload for key in ("cve_ids", "iocs", "assets", "sbom")) else 0
    return structured + _keyword_score(query, _SECURITY_KEYWORDS)


def _run_security(payload: dict[str, Any]) -> dict[str, Any]:
    from react_agent.apps.security_triage.offline_answer import answer_offline

    return answer_offline(payload)


def _verify_security(output: dict[str, Any]) -> dict[str, bool]:
    case = output.get("case") or {}
    return {
        "triage_completed": bool(output.get("ok") and case.get("schema_version") == "security-triage/v1"),
        "citations_present": bool(case.get("citations")) or not (case.get("cves") or case.get("iocs")),
        "human_review_gate": case.get("status") == "pending_review",
        "no_actions_executed": case.get("executed_actions") == [],
    }


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


def _run_github_delivery(payload: dict[str, Any]) -> dict[str, Any]:
    from react_agent.apps.github_delivery import (
        Approval,
        DeliveryTask,
        GitHubDeliveryWorkflow,
        WorkflowConfig,
    )

    task = DeliveryTask.from_dict(payload)
    approval_payload = payload.get("approval")
    approval = Approval.from_dict(approval_payload) if approval_payload else None
    config = WorkflowConfig(
        artifact_dir=Path(payload["artifact_dir"]),
        mode=str(payload.get("mode") or "shadow"),
        publish_draft_pr=bool(payload.get("publish_draft_pr", False)),
        max_test_seconds=int(payload.get("max_test_seconds", 120)),
        max_workflow_seconds=int(payload.get("max_workflow_seconds", 300)),
    )
    workflow = GitHubDeliveryWorkflow(config)
    return workflow.run(
        task,
        approval=approval,
        idempotency_key=str(payload["idempotency_key"]),
    )


def _verify_github_delivery(output: dict[str, Any]) -> dict[str, bool]:
    status = str(output.get("status") or "")
    approval_state = (output.get("approval") or {}).get("state")
    write_status = status in {"candidate_committed", "draft_pr_created"}
    return {
        "workflow_terminal": status
        in {
            "shadow_passed",
            "approval_required",
            "candidate_committed",
            "draft_pr_created",
        },
        "unauthorized_external_write_blocked": not bool(
            (output.get("metrics") or {}).get("unauthorized_external_write")
        ),
        "write_requires_bound_approval": not write_status or approval_state == "approved",
        "evaluation_episode_emitted": isinstance(output.get("episode"), dict),
    }


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
        )
    )
    register_skill(
        SkillDef(
            name="security_triage",
            scenario="security_operations_triage",
            description="Read-only CVE/KEV/ATT&CK/IOC triage with asset evidence, citations, and human review gate.",
            version="1",
            workflow="security_triage@1",
            risk_level="read_only",
            owner="security-ai",
            required_inputs=(),
            required_outputs=("answer", "case"),
            allowed_tools=("security_lookup_cve", "security_check_kev", "security_triage_report"),
            instructions=(
                "Use only public intelligence and caller-supplied asset/SBOM evidence.",
                "Mark ATT&CK results as inferred and non-authoritative.",
                "Keep every recommendation not executed and require human review.",
                "Never claim that absence from a source means safe or unaffected.",
            ),
            release_checks=("triage_completed", "citations_present", "human_review_gate", "no_actions_executed"),
            input_schema={"type": "object"},
            output_schema={"type": "object", "required": ["answer", "case"]},
            executor=_run_security,
            verifier=_verify_security,
            matcher=_match_security,
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
        )
    )
    register_skill(
        SkillDef(
            name="github_delivery",
            scenario="software_delivery",
            description="Run isolated change, test, approval, candidate commit, and optional Draft PR flow.",
            version="1",
            workflow="github_delivery@1",
            risk_level="external_write",
            agent_callable=False,
            owner="engineering-platform",
            required_inputs=(
                "task_id",
                "repository",
                "issue_url",
                "replacements",
                "test_command",
                "acceptance_criteria",
                "artifact_dir",
                "idempotency_key",
            ),
            required_outputs=("status", "plan_sha256", "metrics", "episode"),
            allowed_tools=(),
            instructions=(
                "Validate the task and run only an allowlisted test command.",
                "Prepare and test changes in an isolated clone before any commit.",
                "Bind guarded approval to the complete plan hash.",
                "Keep external writes disabled unless explicitly authorized.",
            ),
            release_checks=(
                "workflow_terminal",
                "unauthorized_external_write_blocked",
                "write_requires_bound_approval",
                "evaluation_episode_emitted",
            ),
            input_schema=_GITHUB_INPUT_SCHEMA,
            output_schema=_GITHUB_OUTPUT_SCHEMA,
            executor=_run_github_delivery,
            verifier=_verify_github_delivery,
            matcher=_match_github,
        )
    )
