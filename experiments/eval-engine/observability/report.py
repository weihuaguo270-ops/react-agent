"""report — 结构化评估报告生成

将 ProcessRewardReport + EvalLoopResult 转为：
  - 文本报告（给人看的）
  - 结构化数据（供 dashboard 用）
  - 趋势数据（时间序列，供 baseline 对比）
"""

from __future__ import annotations
import json
import time
from typing import Any


def format_report(
    result: EvalLoopResult,
    detailed: bool = False,
) -> str:
    """将 Eval Loop 结果格式化为可读文本

    参数:
        result:   Eval Loop 执行结果
        detailed: 是否包含每步评分细节（True = 给开发者看）

    返回:
        str: 格式化的文本报告
    """
    lines = []
    lines.append("=" * 55)
    lines.append("  Agent 质量评估报告")
    lines.append("=" * 55)

    intent_label = {
        "functional_test": "功能测试",
        "generative_task": "生成式任务",
    }.get(result.task_type, result.task_type)
    lines.append(f"  任务类型:   {intent_label}")
    lines.append(f"  循环次数:   {result.iterations}")
    lines.append(f"  最终结果:   {'✅ 通过' if result.passed else '❌ 未达标'}")
    lines.append("")

    # 评分概览
    r = result.report
    lines.append(f"  综合评分:   {r.overall_score:.3f} / 5.0")
    lines.append(f"  步骤总数:   {r.num_steps}")
    lines.append(f"  已评分:     {r.num_scored}")
    lines.append(f"  失败步骤:   {r.num_failed_steps}")
    lines.append(f"  通过率:     {r.pass_rate * 100:.0f}%")
    lines.append("")

    # 错误传播
    if result.error_analysis:
        ea = result.error_analysis
        if ea.get("error_sources"):
            lines.append(f"  错误源头: Step {ea['error_sources']}")
            lines.append(f"  直接影响: {ea['impact_summary']['directly_affected']} 步")
            lines.append(f"  级联影响: {ea['impact_summary']['cascading_affected']} 步")
            lines.append(f"  最终答案受影响: {'是' if ea['impact_summary']['final_answer_affected'] else '否'}")
            lines.append("")

    # 自愈日志
    if len(result.healing_log) > 1:
        lines.append(f"  ── 自愈过程 ──")
        for entry in result.healing_log:
            icon = "✅" if not entry["needs_revision"] else "🔄"
            lines.append(
                f"  {icon} 迭代 {entry['iteration']}: "
                f"得分 {entry['overall_score']:.3f}, "
                f"失败 {entry['num_failed_steps']} 步"
            )
        lines.append("")

    # 每步评分细节
    if detailed and r.per_step:
        lines.append(f"  ── 步骤评分明细 ──")
        for step in r.per_step:
            tool = f" ({step.tool_name})" if step.tool_name else ""
            icon = "✅" if not step.needs_revision else "❌"
            lines.append(f"  {icon} Step {step.step_index} [{step.step_type}]{tool}")
            lines.append(f"    评分: {step.step_score:.2f}/5.0")
            if step.role_understanding:
                lines.append(f"    角色: {step.role_understanding[:80]}")
            for rubric in step.rubrics:
                ri = "✅" if not rubric.needs_revision else "❌"
                lines.append(f"    {ri} {rubric.dimension}: {rubric.score:.1f} — {rubric.reason[:60]}")
        lines.append("")

    # 最终输出预览
    lines.append(f"  ── 最终输出（预览） ──")
    lines.append(f"  {result.final_output[:300]}")
    lines.append("")
    lines.append("=" * 55)

    return "\n".join(lines)


def report_to_json(result: EvalLoopResult) -> dict[str, Any]:
    """将 Eval Loop 结果转为结构化 JSON"""
    return {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "query": result.query,
        "task_type": result.task_type,
        "passed": result.passed,
        "iterations": result.iterations,
        "overall_score": result.report.overall_score,
        "summary": {
            "num_steps": result.report.num_steps,
            "num_failed_steps": result.report.num_failed_steps,
            "pass_rate": result.report.pass_rate,
            "error_sources": result.error_analysis.get("error_sources", []),
        },
        "healing_log": [
            {
                "iteration": e["iteration"],
                "score": e["overall_score"],
                "needs_revision": e["needs_revision"],
            }
            for e in result.healing_log
        ],
        "error_analysis": result.error_analysis,
        "final_output_preview": result.final_output[:500],
    }
