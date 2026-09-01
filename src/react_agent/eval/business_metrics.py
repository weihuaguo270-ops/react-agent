"""业务评测共用的结果指标和版本比较工具。

这些函数只负责汇总评测样本，不把本地或合成数据冒充为生产业务证据。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def safe_rate(numerator: int | float, denominator: int | float) -> float:
    """返回限制在 ``[0, 1]`` 的比例；空切片返回零。"""
    if denominator <= 0:
        return 0.0
    return round(max(0.0, min(1.0, float(numerator) / float(denominator))), 3)


def average(values: Iterable[float | int]) -> float | None:
    """返回四舍五入后的均值；没有适用样本时返回 ``None``。"""
    materialized = [float(value) for value in values]
    if not materialized:
        return None
    return round(sum(materialized) / len(materialized), 3)


def business_scorecard(
    rows: Iterable[Mapping[str, Any]],
    *,
    passed_key: str = "passed",
    human_handoff_key: str | None = None,
    duration_key: str | None = None,
) -> dict[str, Any]:
    """汇总一个业务切片的结果、人工介入和时延指标。

    ``rows`` 至少需要包含通过标记；人工介入和时延字段按需传入，未提供时
    不输出对应指标，避免把缺失证据误报成零值。
    """
    materialized = list(rows)
    total = len(materialized)
    # passed 必须由领域验收器写入，不能用最终文本是否非空替代。
    passed = sum(bool(row.get(passed_key)) for row in materialized)
    handoffs = (
        sum(bool(row.get(human_handoff_key)) for row in materialized)
        if human_handoff_key
        else None
    )
    # 只统计明确提供的时延，避免缺失值改变样本量或被当作零毫秒。
    durations = (
        [float(row[duration_key]) for row in materialized if row.get(duration_key) is not None]
        if duration_key
        else []
    )
    metrics: dict[str, Any] = {
        "task_success_rate": safe_rate(passed, total),
        "failure_rate": safe_rate(total - passed, total),
        "sample_size": total,
    }
    if handoffs is not None:
        metrics["human_handoff_rate"] = safe_rate(handoffs, total)
        metrics["human_handoff_count"] = handoffs
    if durations:
        metrics["duration_avg_ms"] = average(durations)
        metrics["duration_p95_ms"] = _percentile(durations, 0.95)
    return metrics


def compare_scorecards(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    hard_metrics: tuple[str, ...] = ("task_success_rate",),
) -> dict[str, Any]:
    """比较两个版本的业务指标，硬指标退化时阻止发布。

    只比较两个版本都存在且为数值的字段；默认将任务成功率作为硬指标，
    其他指标仅记录差值，由调用方决定是否纳入发布门禁。
    """
    deltas: dict[str, float] = {}
    regressions: list[str] = []
    # 只比较共有数值字段，避免样本量或版本号等元数据被误判为回归。
    for key in sorted(set(baseline) & set(candidate)):
        old, new = baseline[key], candidate[key]
        if not isinstance(old, (int, float)) or not isinstance(new, (int, float)):
            continue
        delta = round(float(new) - float(old), 3)
        deltas[key] = delta
        if key in hard_metrics and delta < 0:
            regressions.append(key)
    return {
        "deltas": deltas,
        "hard_metric_regressions": regressions,
        "decision": "hold" if regressions else "pass",
    }


def _percentile(values: list[float], quantile: float) -> float:
    """按近似最近秩计算小规模、确定性评测批次的分位数。"""
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * quantile))))
    return round(ordered[index], 3)


__all__ = ["average", "business_scorecard", "compare_scorecards", "safe_rate"]
