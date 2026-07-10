"""semantic — 语义级分析（B 层）

检测 LLM-as-Judge 才能发现的问题：
  - 事实性：Agent 的最终答案是否基于真实搜索结果，还是编造数据
  - 任务完成度：Agent 是否真的完成了用户要求的全部步骤
  - 搜索利用度：搜索结果是否被实际用于最终答案
  - 幻觉检测：Agent 是否声称找到了不存在的信息
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Optional, Callable

from .reader import Trajectory, Step


@dataclass
class SemanticIssue:
    """语义级问题"""
    type: str           # factuality / completion / search_use / hallucination
    severity: str       # high / medium / low
    description: str    # 问题描述
    evidence: str       # 证据（从轨迹中摘取的关键片段）
    suggestion: str     # 修复建议


@dataclass
class SemanticReport:
    """语义分析报告"""
    issues: list[SemanticIssue] = field(default_factory=list)
    factuality_score: float = 5.0        # 事实性评分 1-5
    completion_score: float = 5.0        # 完成度评分 1-5
    summary: str = ""

    @property
    def has_issues(self) -> bool:
        return len(self.issues) > 0

    @property
    def high_severity_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "high")


class SemanticAnalyzer:
    """语义分析器 — 接入 LLM Judge 检测深层问题

    用法：
        analyzer = SemanticAnalyzer(judge_fn=call_llm)
        report = analyzer.analyze(traj, traj_analysis)
    """

    def __init__(self, judge_fn: Optional[Callable[[str], dict[str, Any]]] = None):
        self.judge_fn = judge_fn

    def analyze(
        self,
        traj: Trajectory,
        analysis: Any,  # TrajectoryAnalysis
    ) -> SemanticReport:
        """执行语义分析"""
        report = SemanticReport()

        # 规则检测（不需要 Judge）
        fact_issues = self._check_factuality(traj, analysis)
        report.issues.extend(fact_issues)
        completion_issues = self._check_completion(traj, analysis)
        report.issues.extend(completion_issues)
        search_issues = self._check_search_utilization(traj, analysis)
        report.issues.extend(search_issues)

        # LLM 检测（需要 Judge）
        if self.judge_fn:
            llm_issues = self._check_with_llm(traj, analysis)
            report.issues.extend(llm_issues)

        # 计算评分
        if report.issues:
            high = sum(1 for i in report.issues if i.severity == "high")
            medium = sum(1 for i in report.issues if i.severity == "medium")
            report.factuality_score = max(1.0, 5.0 - high * 1.5 - medium * 0.5)
            report.completion_score = max(1.0, 5.0 - sum(
                1 for i in report.issues if i.type == "completion"
            ) * 1.0)

        # 汇总
        if not report.issues:
            report.summary = "语义分析未发现明显问题"
        else:
            severity_counts = {}
            for i in report.issues:
                severity_counts[i.severity] = severity_counts.get(i.severity, 0) + 1
            parts = [f"发现 {len(report.issues)} 个语义问题"]
            for s, c in sorted(severity_counts.items()):
                parts.append(f"{s} {c} 个")
            report.summary = "，".join(parts)

        return report

    def _check_factuality(self, traj: Trajectory, analysis: TrajectoryAnalysis) -> list[SemanticIssue]:
        """事实性检测：最终答案是否有依据"""
        issues = []

        # 收集搜索到的内容
        search_results = []
        for step in traj.steps:
            if step.action_name in ("web_search", "fetch_page") and step.observation:
                search_results.append(step.observation[:200])

        # 最终答案
        final = traj.final_answer
        if not final:
            issues.append(SemanticIssue(
                type="factuality",
                severity="high",
                description="Agent 未给出最终答案，执行被强制终止",
                evidence=f"执行了 {traj.num_steps} 步后停止，无 final_answer",
                suggestion="任务过于复杂，建议拆分为多步或增加最大步数",
            ))
            return issues

        # 如果没有搜索到内容但生成了大量分析，可能是编造
        if not search_results and len(final) > 100:
            evidence = final[:200]
            issues.append(SemanticIssue(
                type="factuality",
                severity="high",
                description="Agent 未搜索到任何信息却生成了详细回答，可能包含编造内容",
                evidence=evidence,
                suggestion="检查最终答案中的数据是否真实可验证",
            ))

        # 如果有搜索记录但没 fetch_page，可能信息不足
        raw_data_text = " ".join(search_results)
        if len(raw_data_text) < 100 and len(final) > 500:
            evidence = f"搜索到 {len(raw_data_text)} 字符，生成了 {len(final)} 字符回答"
            issues.append(SemanticIssue(
                type="factuality",
                severity="medium",
                description="搜索到的信息量远少于生成的回答量，可能存在编造",
                evidence=evidence,
                suggestion="确认回答中的数据来源是否可靠",
            ))

        return issues

    def _check_completion(self, traj: Trajectory, analysis: TrajectoryAnalysis) -> list[SemanticIssue]:
        """任务完成度检测"""
        issues = []
        query = traj.query

        # 检查用户是否要求了多个子任务
        task_markers = []
        if "搜索" in query or "查找" in query or "找" in query:
            task_markers.append("搜索/查找")
        if "分析" in query or "总结" in query or "对比" in query:
            task_markers.append("分析/总结")
        if "代码" in query or "Python" in query or "实现" in query:
            task_markers.append("编码/实现")

        # 如果要求了多步但步骤太少
        if len(task_markers) >= 2 and traj.num_steps < len(task_markers) * 2:
            issues.append(SemanticIssue(
                type="completion",
                severity="high",
                description=f"用户要求多个步骤（{' + '.join(task_markers)}），但执行步数（{traj.num_steps}步）可能不足",
                evidence=f"要求: {task_markers}, 实际: {traj.num_steps}步",
                suggestion="检查是否有子任务被遗漏或跳过",
            ))

        # 搜索过但没有阅读搜索结果
        has_search = any(s.action_name == "web_search" for s in traj.steps)
        has_fetch = any(s.action_name == "fetch_page" for s in traj.steps)
        if has_search and not has_fetch:
            issues.append(SemanticIssue(
                type="completion",
                severity="medium",
                description="执行了搜索但没有阅读任何搜索结果页面",
                evidence="web_search 已执行但 fetch_page 从未调用",
                suggestion="搜索后应阅读结果页面以获取完整信息",
            ))

        return issues

    def _check_with_llm(self, traj: Trajectory, analysis: Any) -> list[SemanticIssue]:
        """LLM 辅助的语义检测（需要 judge_fn）"""
        issues = []
        if not self.judge_fn:
            return issues

        # 构建检测 prompt
        steps_summary = []
        for s in traj.steps:
            if s.action_name:
                steps_summary.append(f"Step {s.index}: 调 {s.action_name}")
            elif s.is_final:
                steps_summary.append(f"Step {s.index}: 输出答案")
            elif s.thought:
                steps_summary.append(f"Step {s.index}: 思考")

        prompt = f"""分析以下 Agent 执行轨迹，判断是否存在以下问题：

用户需求：{traj.query[:200]}

执行步骤：
{chr(10).join(steps_summary)}

最终答案：{traj.final_answer[:500] if traj.final_answer else '(无)'}

请检测：
1. 幻觉：Agent 是否编造了搜索结果中不存在的信息？
2. 任务遗漏：用户要求的步骤是否有未被执行的？
3. 结论可靠性：最终答案是否有充分的数据支撑？

输出 JSON：
{{"hallucination_risk": "high/medium/low", "hallucination_detail": "...",
  "task_missed": ["遗漏项1"], "conclusion_risk": "high/medium/low",
  "overall_assessment": "..."}}"""

        try:
            result = self.judge_fn(prompt)
            if isinstance(result, dict):
                risk = result.get("hallucination_risk", "low")
                if risk == "high":
                    issues.append(SemanticIssue(
                        type="hallucination", severity="high",
                        description=f"存在高幻觉风险: {result.get('hallucination_detail', '')[:100]}",
                        evidence=result.get("hallucination_detail", "")[:150],
                        suggestion="核实最终答案中每个数据点的出处",
                    ))
                missed = result.get("task_missed", [])
                for m in missed:
                    issues.append(SemanticIssue(
                        type="completion", severity="medium",
                        description=f"可能遗漏了子任务: {m}",
                        evidence=m, suggestion="检查是否需要补充执行",
                    ))
        except Exception as e:
            issues.append(SemanticIssue(
                type="hallucination", severity="low",
                description=f"LLM 分析异常: {e}",
                evidence="", suggestion="",
            ))

        return issues

    def _check_search_utilization(self, traj: Trajectory, analysis: Any) -> list[SemanticIssue]:
        """搜索利用度检测"""
        issues = []

        # 检查是否有大量搜索但后续没有利用
        search_actions = [s for s in traj.steps if s.action_name == "web_search"]
        post_search_actions = [s for s in traj.steps if s.index > (search_actions[-1].index if search_actions else -1)]

        if len(search_actions) >= 3 and not any(
            s.action_name in ("fetch_page", "summarize") for s in post_search_actions
        ):
            issues.append(SemanticIssue(
                type="search_use",
                severity="medium",
                description=f"执行了 {len(search_actions)} 次搜索但未深入阅读任何结果",
                evidence="多次搜索后没有 fetch_page 或 summarize 步骤",
                suggestion="搜索后应阅读至少 1-2 个结果页面获取详细信息",
            ))

        return issues
