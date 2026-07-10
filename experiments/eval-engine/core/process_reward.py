"""process_reward — 步骤级 Process Reward 评分（核心创新）

评分思路（受 o1/o3 Process Reward Model 启发）：
    传统 Eval：只看最终答案 → 对/错 二分
    Process Reward：对每一步，基于"当时上下文"判断"这个决策是否合理"

核心逻辑：
    1. 对 DAG 的每个节点，构建该步骤的上下文
    2. 用动态 Rubric 生成（dynamic_rubric.py）生成评分标准
    3. 调用 Judge LLM 按标准逐条打分
    4. 汇总每步得分 → 最终加权总分
    5. 追踪错误传播

输出：
    ProcessRewardReport:
        - per_step:         每步的评分详情
        - overall_score:    加权总分
        - error_sources:    根因步骤
        - needs_revision:   是否需要修正
        - healing_log:      自愈过程记录（如果启用了在线修正）
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Optional, Callable

from core.trajectory_parser import StepsDAG, dag_summary
from core.dynamic_rubric import (
    build_step_context,
    build_step_judge_prompt,
    build_trajectory_judge_prompt,
)
from core.contract import VerifierContract


# ──────────────────────────────────────────────
# 数据结构
# ──────────────────────────────────────────────


@dataclass
class RubricResult:
    """单条评分标准的结果"""
    dimension: str         # 维度名
    criteria: str          # 评分标准
    score: float           # 得分 [1, 5]
    reason: str            # 评分理由
    needs_revision: bool = False  # 是否低于阈值


@dataclass
class StepScore:
    """单步的 Process Reward 评分结果"""
    step_index: int
    step_type: str
    tool_name: Optional[str]
    rubrics: list[RubricResult]
    step_score: float            # 该步平均分
    needs_revision: bool = False
    role_understanding: str = ""  # Judge 对该步角色的理解


@dataclass
class ProcessRewardReport:
    """Process Reward 评分报告"""
    query: str
    per_step: list[StepScore]
    overall_score: float         # 所有步骤的加权平均
    num_steps: int
    num_scored: int
    num_failed_steps: int        # 需要修正的步骤数
    error_sources: list[int]     # 根因步骤索引
    needs_revision: bool         # 是否有任何一步需修正
    healing_log: list[dict]      # 自愈记录（如有）
    dag_summary: dict

    @property
    def pass_rate(self) -> float:
        """通过率：无需修正的步骤占比"""
        if self.num_scored == 0:
            return 0.0
        return 1.0 - (self.num_failed_steps / self.num_scored)

    @property
    def worst_steps(self) -> list[StepScore]:
        """返回得分最低的步骤（供修正用）"""
        sorted_steps = sorted(self.per_step, key=lambda s: s.step_score)
        return [s for s in sorted_steps if s.needs_revision]


# ──────────────────────────────────────────────
# Process Reward 评分器
# ──────────────────────────────────────────────


class ProcessRewardScorer:
    """Process Reward 评分器

    对 Agent 执行轨迹的每一步进行评分。

    用法：
        scorer = ProcessRewardScorer(judge_fn=my_llm_call)
        report = scorer.score_trajectory(dag)
    """

    def __init__(
        self,
        judge_fn: Callable[[str], dict[str, Any]],
        min_step_score: float = 3.5,
        extra_contracts: Optional[list[VerifierContract]] = None,
    ) -> None:
        """初始化评分器

        参数:
            judge_fn:   Judge LLM 调用函数。
                       输入 prompt 字符串，输出解析后的 JSON 字典。
            min_step_score: 单步最低分阈值（低于此标记为 needs_revision）
            extra_contracts: 额外的固定契约（在动态标准之外补充）
        """
        self.judge_fn = judge_fn
        self.min_step_score = min_step_score
        self.extra_contracts = extra_contracts or []

    def score_trajectory(
        self,
        dag: StepsDAG,
        fast_mode: bool = False,
    ) -> ProcessRewardReport:
        """对整条轨迹执行 Process Reward 评分

        参数:
            dag:        解析后的 StepsDAG
            fast_mode:  快速模式。为 True 时只做整体评估，不逐步骤深入

        返回:
            ProcessRewardReport: 完整评分报告
        """
        if fast_mode:
            return self._score_fast(dag)

        return self._score_step_by_step(dag)

    def _score_fast(self, dag: StepsDAG) -> ProcessRewardReport:
        """快速模式：整体评估，不逐步骤"""
        prompt = build_trajectory_judge_prompt(dag)
        try:
            result = self.judge_fn(prompt)
        except Exception as e:
            # Judge 调用失败，返回兜底报告
            result = {
                "overall_score": 0,
                "efficiency_score": 0,
                "tool_usage_score": 0,
                "strengths": [],
                "weaknesses": [f"Judge 调用异常: {e}"],
                "needs_revision": True,
            }

        scores = [
            result.get("overall_score", 0),
            result.get("efficiency_score", 0),
            result.get("tool_usage_score", 0),
        ]
        overall = sum(scores) / len(scores) if scores else 0

        return ProcessRewardReport(
            query=dag.query,
            per_step=[
                StepScore(
                    step_index=-1,
                    step_type="fast_eval",
                    tool_name=None,
                    rubrics=[
                        RubricResult(
                            dimension="overall",
                            criteria="整体质量评估",
                            score=result.get("overall_score", 0),
                            reason="",
                        ),
                    ],
                    step_score=overall,
                    needs_revision=result.get("needs_revision", False),
                ),
            ],
            overall_score=overall,
            num_steps=dag.num_steps,
            num_scored=1,
            num_failed_steps=1 if result.get("needs_revision", False) else 0,
            error_sources=[],
            needs_revision=result.get("needs_revision", False),
            healing_log=[],
            dag_summary=dag_summary(dag),
        )

    def _score_step_by_step(self, dag: StepsDAG) -> ProcessRewardReport:
        """逐步骤评分模式

        对 DAG 中的每个节点：
          1. 构建该步的上下文
          2. 生成 Judge prompt
          3. 调用 Judge LLM 评分
          4. 记录结果
        """
        step_scores: list[StepScore] = []
        error_sources: list[int] = []

        for node in dag.nodes:
            context = build_step_context(dag, node.step_index)
            prompt = build_step_judge_prompt(context)

            try:
                judge_output = self.judge_fn(prompt)
            except Exception as e:
                # Judge 调用失败，使用占位分数
                judge_output = {
                    "role_understanding": f"Judge 调用异常: {e}",
                    "rubrics": [
                        {"dimension": "error", "criteria": "Judge 异常",
                         "score": 0, "reason": str(e)},
                    ],
                    "step_score": 0,
                    "needs_revision": True,
                }

            rubrics = []
            for r in judge_output.get("rubrics", []):
                rubrics.append(RubricResult(
                    dimension=r.get("dimension", "unknown"),
                    criteria=r.get("criteria", ""),
                    score=float(r.get("score", 3)),
                    reason=r.get("reason", ""),
                    needs_revision=float(r.get("score", 3)) <= 3,
                ))

            step_score_val = float(judge_output.get("step_score", 3))
            needs_revision = judge_output.get("needs_revision", False) or (
                step_score_val < self.min_step_score
            )

            step_scores.append(StepScore(
                step_index=node.step_index,
                step_type=node.step_type,
                tool_name=node.tool_name,
                rubrics=rubrics,
                step_score=step_score_val,
                needs_revision=needs_revision,
                role_understanding=judge_output.get("role_understanding", ""),
            ))

            # 记录分数到 DAG 节点
            node.score = step_score_val

        # 定位根因
        error_sources = [n.step_index for n in dag.find_error_sources()]

        # 计算加权总分
        scored_steps = [s for s in step_scores if s.step_score > 0]
        if scored_steps:
            # 按是否根因加权：根因步骤权重大
            total_weight = 0
            weighted_sum = 0.0
            for s in scored_steps:
                weight = 1.5 if s.step_index in error_sources else 1.0
                weighted_sum += s.step_score * weight
                total_weight += weight
            overall = weighted_sum / total_weight if total_weight > 0 else 0.0
        else:
            overall = 0.0

        return ProcessRewardReport(
            query=dag.query,
            per_step=step_scores,
            overall_score=round(overall, 3),
            num_steps=dag.num_steps,
            num_scored=len(scored_steps),
            num_failed_steps=sum(1 for s in step_scores if s.needs_revision),
            error_sources=error_sources,
            needs_revision=any(s.needs_revision for s in step_scores),
            healing_log=[],
            dag_summary=dag_summary(dag),
        )


# ──────────────────────────────────────────────
# 错误传播分析
# ──────────────────────────────────────────────


def analyze_error_propagation(
    report: ProcessRewardReport,
    dag: StepsDAG,
) -> dict[str, Any]:
    """分析错误传播路径

    对 ProcessRewardReport 中的失败步骤，追踪其影响范围。

    返回:
        {
            "error_sources": [根因步骤索引],
            "propagation_paths": [
                {"from": 步骤A, "to": 步骤B, "relation": "output_to_input"},
                ...
            ],
            "impact_summary": {
                "直接影响步骤数": N,
                "间接影响步骤数": M,
                "最终答案受影响": True/False,
            }
        }
    """
    error_sources = report.error_sources
    propagation_paths = []
    affected_steps: set[int] = set()

    for source_idx in error_sources:
        downstream = dag.get_downstream(source_idx)
        for down_node in downstream:
            propagation_paths.append({
                "from": source_idx,
                "to": down_node.step_index,
                "relation": "error_propagate",
            })
            affected_steps.add(down_node.step_index)

            # BFS 继续追踪下游的下游
            sub_downstream = dag.get_downstream(down_node.step_index)
            for sub in sub_downstream:
                if sub.step_index not in affected_steps:
                    propagation_paths.append({
                        "from": down_node.step_index,
                        "to": sub.step_index,
                        "relation": "cascading",
                    })
                    affected_steps.add(sub.step_index)

    final_affected = any(
        s.step_type == "final" and s.step_index in affected_steps
        for s in dag.nodes
    )

    return {
        "error_sources": error_sources,
        "propagation_paths": propagation_paths,
        "impact_summary": {
            "directly_affected": len(
                set(p["to"] for p in propagation_paths if p["relation"] == "error_propagate")
            ),
            "cascading_affected": len(
                set(p["to"] for p in propagation_paths if p["relation"] == "cascading")
            ),
            "final_answer_affected": final_affected,
        },
    }


# ──────────────────────────────────────────────
# 修正指令打包
# ──────────────────────────────────────────────


def pack_revision_instructions(
    report: ProcessRewardReport,
    dag: StepsDAG,
) -> str:
    """将低分项打包为结构化修正指令（供 LLM 重新生成时使用）

    参数:
        report: Process Reward 评分报告
        dag:    原始 StepsDAG

    返回:
        str: 修正指令，可直接作为 LLM 的 feedback 输入
    """
    if not report.needs_revision:
        return "所有步骤质量达标，无需修正。"

    worst = report.worst_steps
    lines = [
        "以下步骤需要修正：",
    ]

    for step in worst[:5]:  # 最多修正 5 步
        node = dag.get_node(step.step_index)
        failed_rubrics = [
            r for r in step.rubrics if r.needs_revision
        ]

        tool_info = f"（工具: {node.tool_name}, 参数: {node.tool_args}）" if node and node.tool_name else ""
        lines.append(f"\n  Step {step.step_index} [{step.step_type}] {tool_info}")
        lines.append(f"  当前得分: {step.step_score}/5.0")

        for r in failed_rubrics:
            lines.append(f"    ❌ {r.dimension}: {r.reason}")

        # 如果有根因标记
        if step.step_index in report.error_sources:
            lines.append(f"    ⚠ 这是错误源头，修复它可以减少影响下游步骤")

        # 显示受影响的后续步骤
        if node:
            affected = dag.get_downstream(step.step_index)
            if affected:
                affected_indices = [n.step_index for n in affected]
                lines.append(f"    → 影响下游步骤: {affected_indices}")

    lines.extend([
        "",
        "请根据以上修正意见重新生成。",
        "重点修复标记为 ❌ 的维度，其他维度保持当前水平即可。",
    ])

    return "\n".join(lines)
