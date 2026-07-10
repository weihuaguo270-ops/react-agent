"""calibration — Judge 校准系统

Judge 模型在长期使用中会出现"评分漂移"——同一份输出，1 月和 3 月打的分数可能不一样。
校准的目的就是定期对齐 Judge 与人类标注的标准。

核心流程：
  1. 准备一组已有人类标注的"金标准"用例（约 50-100 条）
  2. Judge 对这组用例重新评分
  3. 计算 Cohen's κ 系数（衡量 Judge 与人类的一致性）
  4. 如果 κ < 0.7，说明 Judge 漂移了，需要校准
  5. 校准方法：调整评分 prompt 的措辞，或提供 few-shot 示例

数据流：
    calibration_data.json  →  JudgeRecommender.run()  →  校准报告
        [人类评分]                                        [κ 系数]
        [Judge 评分]                                      [漂移检测]
                                                          [校准建议]
"""

from __future__ import annotations
import json
import math
from typing import Any, Callable, Optional


# ──────────────────────────────────────────────
# Cohen's κ 计算
# ──────────────────────────────────────────────


def cohens_kappa(
    human_scores: list[float],
    judge_scores: list[float],
    n_bins: int = 5,
) -> float:
    """计算 Cohen's κ 系数

    κ = (Po - Pe) / (1 - Pe)
      Po = 观察一致性（Judge 与人类评分相同的比例）
      Pe = 期望一致性（随机情况下一致的期望概率）

    参数:
        human_scores:  人类评分列表 [1, 2, 3, 4, 5, ...]
        judge_scores:  Judge 评分列表 [1.0, 2.5, 3.0, ...]
        n_bins:        分箱数（将连续评分离散化）

    返回:
        float: κ 系数，范围 [-1, 1]
               κ > 0.8  → 几乎完全一致
               κ 0.6-0.8 → 高度一致
               κ 0.4-0.6 → 中等一致
               κ < 0.4   → 一致性差，需要校准
    """
    if len(human_scores) != len(judge_scores) or len(human_scores) == 0:
        return 0.0

    n = len(human_scores)

    # 离散化到 n 个 bins
    def _discretize(scores: list[float], bins: int) -> list[int]:
        min_s, max_s = min(scores), max(scores)
        if max_s == min_s:
            return [0] * len(scores)
        return [
            min(bins - 1, int((s - min_s) / (max_s - min_s + 1e-6) * bins))
            for s in scores
        ]

    h_binned = _discretize(human_scores, n_bins)
    j_binned = _discretize(judge_scores, n_bins)

    # 构建混淆矩阵
    matrix = [[0] * n_bins for _ in range(n_bins)]
    for h, j in zip(h_binned, j_binned):
        matrix[h][j] += 1

    # Po: 观察一致性
    po = sum(matrix[i][i] for i in range(n_bins)) / n

    # Pe: 期望一致性
    row_sums = [sum(row) for row in matrix]
    col_sums = [sum(matrix[i][j] for i in range(n_bins)) for j in range(n_bins)]
    pe = sum(row_sums[i] * col_sums[i] for i in range(n_bins)) / (n * n)

    if pe >= 1.0:
        return 1.0

    return round((po - pe) / (1 - pe), 4)


# ──────────────────────────────────────────────
# 校准检查
# ──────────────────────────────────────────────


class JudgeCalibrator:
    """Judge 校准器

    用法：
        calibrator = JudgeCalibrator()
        calibrator.load_golden("judge_calibration_data.json")
        report = calibrator.run(judge_fn=my_judge)
        if report["needs_calibration"]:
            print(f"κ={report['kappa']}，需要校准")
    """

    def __init__(self, threshold: float = 0.7):
        """初始化校准器

        参数:
            threshold: Cohen's κ 阈值，低于此值触发校准警告
        """
        self.threshold = threshold
        self.golden_data: list[dict] = []

    def load_golden(self, data: list[dict]) -> None:
        """加载金标准数据

        参数:
            data: [{"prompt": str, "human_score": float, "expected_rubrics": ...}, ...]
        """
        self.golden_data = data

    def run(
        self,
        judge_fn: Callable[[str], dict[str, Any]],
    ) -> dict[str, Any]:
        """运行校准检查

        参数:
            judge_fn: Judge 调用函数

        返回:
            {
                "kappa": float,           # Cohen's κ
                "needs_calibration": bool, # 是否需校准
                "sample_size": int,
                "avg_human": float,
                "avg_judge": float,
                "drift": float,            # 平均分差
                "worst_dimensions": [...], # 偏差最大的维度
            }
        """
        if not self.golden_data:
            return {
                "kappa": 1.0,
                "needs_calibration": False,
                "sample_size": 0,
                "error": "没有金标准数据",
            }

        human_scores: list[float] = []
        judge_scores: list[float] = []
        dimension_drifts: dict[str, list[float]] = {}

        for item in self.golden_data:
            prompt = item.get("prompt", "")
            human_score = item.get("human_score", 3.0)

            try:
                judge_result = judge_fn(prompt)
            except Exception:
                continue

            # 提取 Judge 评分
            rubrics = judge_result.get("rubrics", [])
            if rubrics:
                judge_score = sum(r.get("score", 3) for r in rubrics) / len(rubrics)
            else:
                judge_score = judge_result.get("step_score", judge_result.get("score", 3.0))

            human_scores.append(human_score)
            judge_scores.append(judge_score)

            # 按维度追踪漂移
            for r in rubrics:
                dim = r.get("dimension", "unknown")
                if dim not in dimension_drifts:
                    dimension_drifts[dim] = []
                # 暂时只记录 Judge 的分数，与人类标注的比较在汇总时做
                dimension_drifts[dim].append(r.get("score", 3))

        # 计算 κ
        kappa = cohens_kappa(human_scores, judge_scores)

        # 计算平均漂移
        avg_human = sum(human_scores) / len(human_scores) if human_scores else 0
        avg_judge = sum(judge_scores) / len(judge_scores) if judge_scores else 0

        # 找到偏差最大的维度
        worst_dims = sorted(
            dimension_drifts.items(),
            key=lambda x: abs(sum(x[1]) / len(x[1]) - avg_human),
            reverse=True,
        )[:3]

        return {
            "kappa": kappa,
            "needs_calibration": kappa < self.threshold,
            "sample_size": len(human_scores),
            "avg_human": round(avg_human, 3),
            "avg_judge": round(avg_judge, 3),
            "drift": round(avg_judge - avg_human, 3),
            "worst_dimensions": [
                {"dimension": d, "avg_score": round(sum(v) / len(v), 2)}
                for d, v in worst_dims
            ],
        }


# ──────────────────────────────────────────────
# 校准数据格式示例
# ──────────────────────────────────────────────

CALIBRATION_DATA_EXAMPLE = [
    {
        "prompt": "评估 Agent 在步骤 1 中的表现...",
        "human_score": 4.0,
        "human_rubrics": [
            {"dimension": "tool_selection", "score": 4, "reason": "工具选择合理"},
        ],
        "expected_step_score": 4.0,
    },
]
