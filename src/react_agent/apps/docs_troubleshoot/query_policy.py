"""请求难度与证据策略分类。

分类只用于决定默认流程和资源预算，不替代模型回答，也不把难度等同于正确率。
"""
from __future__ import annotations

import re
from typing import Any


_STRUCTURED = ("error_response", "log_excerpt", "trace_context", "request_headers")
_COMPLEX = ("分别", "对比", "根因", "依赖", "多服务", "trace", "链路", "为什么")
_INTERNAL = (
    "文档", "排障", "故障", "api", "接口", "错误码", "日志", "runbook", "内部",
    "分页", "cursor", "limit", "cors", "跨域", "预检", "webhook", "回调", "签名",
    "路由", "响应头", "环境变量", "版本", "schema", "轨迹", "toolguard", "请求头",
    "状态码", "重试", "鉴权", "bearer", "token", "项目", "当前项目", "默认", "配置",
)


def classify_query_difficulty(query: str, state: dict[str, Any] | None = None) -> dict[str, Any]:
    """按问题结构选择预算和证据路线。

    这里判断的是流程复杂度，不是模型能力，也不是答案正确率：问题越需要
    现场字段、多来源资料或多步因果分析，允许的工具步数越多。
    """
    text = str(query or "").strip()
    payload = state or {}
    signals: list[str] = []
    if any(payload.get(key) for key in _STRUCTURED):
        signals.append("structured_evidence")
    if len(text) > 240:
        signals.append("long_query")
    if any(token.lower() in text.lower() for token in _COMPLEX):
        signals.append("multi_step_or_root_cause")
    if re.search(r"\b(401|403|404|429|500|502|504)\b", text):
        signals.append("http_error")
    if any(token.lower() in text.lower() for token in _INTERNAL):
        signals.append("internal_evidence")
    # 现场结构化数据和根因/多服务问题必然是复杂任务；多个约束信号也
    # 需要更大的工具预算。单个项目事实信号归为 standard，而非 trivial。
    if (
        "structured_evidence" in signals
        or "multi_step_or_root_cause" in signals
        or len(signals) >= 2
    ):
        level = "complex"
    elif signals:
        level = "standard"
    else:
        level = "trivial"
    dimensions = {
        "evidence": "现场字段" if "structured_evidence" in signals else ("项目资料" if "internal_evidence" in signals else "无内部证据要求"),
        "reasoning": "根因或多步分析" if "multi_step_or_root_cause" in signals else "单步回答",
        "input_size": "长问题" if "long_query" in signals else "短问题",
        "http_context": "包含 HTTP 错误" if "http_error" in signals else "无 HTTP 错误",
    }
    return {
        "level": level,
        "signals": signals,
        "dimensions": dimensions,
        "requires_internal_retrieval": "internal_evidence" in signals or "structured_evidence" in signals,
        "recommended_max_steps": {"trivial": 3, "standard": 6, "complex": 12}[level],
    }


__all__ = ["classify_query_difficulty"]
