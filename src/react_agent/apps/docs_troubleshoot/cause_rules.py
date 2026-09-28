"""Data-driven cause / fix / verify rules keyed by field evidence."""
from __future__ import annotations

from typing import Any

Rule = dict[str, Any]

RULES: list[Rule] = [
    {
        "id": "auth_401",
        "match_status": {401},
        "match_codes": {"unauthorized", ""},
        "causes": [
            {
                "cause": "缺少或格式错误的 Authorization Bearer Token",
                "confidence": "high",
                "doc_hints": ["api_auth.md"],
            }
        ],
        "verify_actions": [
            "确认请求头含 Authorization: Bearer <API_KEY>",
            "对照 api_auth.md 中 401 unauthorized 说明",
        ],
        "fix_steps": [
            "在客户端添加 Authorization: Bearer <API_KEY>（只读配置检查，勿提交密钥）",
        ],
    },
    {
        "id": "rate_429",
        "match_status": {429},
        "match_codes": {"rate_limited", ""},
        "causes": [
            {
                "cause": "触发 API 速率限制（rate_limited）",
                "confidence": "high",
                "doc_hints": ["api_rate_limit.md", "api_errors.md"],
            }
        ],
        "verify_actions": [
            "确认响应 HTTP 429 且 error.code=rate_limited",
            "检查响应头 Retry-After 并按秒数退避",
            "检查调用频率是否超过文档默认配额",
        ],
        "fix_steps": [
            "退避重试并降低并发；必要时申请提额",
        ],
    },
    {
        "id": "invalid_400",
        "match_status": {400},
        "match_codes": {"invalid_request", ""},
        "causes": [
            {
                "cause": "请求体或 cursor 参数非法（invalid_request）",
                "confidence": "high",
                "doc_hints": ["api_errors.md", "api_pagination.md"],
            }
        ],
        "verify_actions": [
            "核对 pagination cursor 是否过期或拼写错误",
            "对照 OpenAPI / api_pagination.md 参数约束",
        ],
        "fix_steps": [
            "使用上一页响应中的 next_cursor 重新请求",
        ],
    },
    {
        "id": "webhook_410",
        "match_status": {410},
        "match_codes": {"webhook_disabled", ""},
        "causes": [
            {
                "cause": "Webhook 订阅 URL 被禁用",
                "confidence": "high",
                "doc_hints": ["api_webhooks.md"],
            }
        ],
        "verify_actions": ["确认 HTTP 410 与 webhook_disabled"],
        "fix_steps": ["在控制台重新启用订阅 URL 或更换 endpoint"],
    },
    {
        "id": "api_sunset",
        "match_query_any": ["sunset", "下线", "废弃", "/v1 只读"],
        "causes": [
            {
                "cause": "v1 只读路由在响应头携带 Sunset 下线信号",
                "confidence": "high",
                "doc_hints": ["api_versioning.md"],
            }
        ],
        "verify_actions": ["检查响应头是否含 Sunset 及下线日期"],
        "fix_steps": ["规划迁移至 /v2 Beta 路径"],
    },
    {
        "id": "cors_preflight",
        "match_headers": {"origin": True},
        "match_query_any": ["cors", "跨域", "预检", "preflight"],
        "causes": [
            {
                "cause": "浏览器 CORS 预检（OPTIONS）未通过",
                "confidence": "medium",
                "doc_hints": ["runbook_cors.md"],
            }
        ],
        "verify_actions": [
            "确认预检使用 OPTIONS 方法",
            "检查 REACT_AGENT_CORS_ORIGINS 是否包含前端 Origin",
        ],
        "fix_steps": [
            "在服务端配置 Access-Control-Allow-Origin 允许来源",
        ],
    },
]


def _field_evidence(evidence_bundle: dict[str, Any]) -> dict[str, Any]:
    http_status = 0
    error_code = ""
    has_origin = False
    for item in evidence_bundle.get("items") or []:
        if item.get("type") == "http_error":
            http_status = int(item.get("status_code") or 0)
            error_code = str(item.get("error_code") or "").lower()
        if item.get("type") == "request_headers":
            hdrs = item.get("headers") or {}
            has_origin = any(k.lower() == "origin" for k in hdrs)
    return {
        "http_status": http_status,
        "error_code": error_code,
        "has_origin": has_origin,
    }


def match_cause_rules(
    *,
    query: str,
    evidence_bundle: dict[str, Any],
) -> list[Rule]:
    """按结构化现场证据命中可解释根因规则。"""
    field = _field_evidence(evidence_bundle)
    ql = (query or "").lower()
    matched: list[Rule] = []
    for rule in RULES:
        st = rule.get("match_status")
        if st and field["http_status"] not in st:
            continue
        codes = rule.get("match_codes")
        if codes is not None and field["error_code"] not in codes:
            if field["error_code"] != "":
                continue
        if rule.get("match_headers", {}).get("origin") and not field["has_origin"]:
            continue
        q_any = rule.get("match_query_any") or []
        if q_any and not any(k.lower() in ql for k in q_any):
            continue
        matched.append(rule)
    return matched


def aggregate_from_rules(rules: list[Rule]) -> dict[str, Any]:
    """聚合规则命中为根因、置信度和修复建议。"""
    causes: list[dict[str, Any]] = []
    verify: list[str] = []
    fixes: list[str] = []
    for r in rules:
        causes.extend(r.get("causes") or [])
        for v in r.get("verify_actions") or []:
            if v not in verify:
                verify.append(v)
        for f in r.get("fix_steps") or []:
            if f not in fixes:
                fixes.append(f)
    return {"causes": causes, "verify_actions": verify, "fix_steps": fixes}


def evidence_sufficiency(
    evidence_bundle: dict[str, Any],
    rules: list[Rule],
    *,
    doc_causes: list[dict[str, Any]] | None = None,
    field_doc_aligned: bool = False,
) -> float | None:
    """现场证据充分度；纯文档问答不适用该指标。"""
    n = int(evidence_bundle.get("count") or 0)
    if n == 0:
        return None
    score = 0.25
    kinds = {item.get("type") for item in evidence_bundle.get("items") or []}
    if "http_error" in kinds:
        score += 0.2
    if kinds & {"log_excerpt", "trace_context"}:
        score += 0.15
    if rules:
        score += min(0.25, 0.15 * len(rules))
    if doc_causes:
        score += min(0.2, 0.08 * len(doc_causes))
    if field_doc_aligned:
        score += 0.2
    return min(1.0, round(score, 3))
