"""regression_gate — 回归门禁

用于 CI/CD 集成，在 PR 或部署前自动检查 Agent 质量是否回退。

使用方式（CLI）：
    # PR 级快速检测（只跑核心用例）
    python -m eval_engine gates --mode pr

    # 完整回归测试
    python -m eval_engine gates --mode full

    # 对比 baseline
    python -m eval_engine gates --compare

通过/阻塞规则：
    - 任何维度下降超过 0.1（5 分制）→ 阻塞
    - 新增失败用例超过 2 条 → 阻塞
    - 核心类别（rag, search）下降超过 0.05 → 阻塞
    - 其他情况 → 允许通过，但记录警告
"""

from __future__ import annotations
import json
import time
from typing import Any, Optional

from gates.baseline import BaselineManager


DEFAULT_REGRESSION_THRESHOLD = 0.1   # 5 分制下的质量下降阈值
CORE_CATEGORIES = ["rag", "search"]  # 核心分类（更严格的阈值）
CORE_THRESHOLD = 0.05


class RegressionGate:
    """回归门禁

    用法：
        gate = RegressionGate()
        result = gate.evaluate(current_report)
        if result["blocked"]:
            print(f"❌ 质量回退，合并阻塞: {result['message']}")
            exit(1)
        else:
            print(f"✅ 通过: {result['message']}")
    """

    def __init__(
        self,
        baseline_manager: Optional[BaselineManager] = None,
        threshold: float = DEFAULT_REGRESSION_THRESHOLD,
    ):
        self.baseline = baseline_manager or BaselineManager()
        self.threshold = threshold

    def evaluate(self, current_report: dict) -> dict[str, Any]:
        """评估当前结果是否有回归

        参数:
            current_report: 当前评测结果（与 report_to_json 兼容）

        返回:
            {
                "passed": bool,        # 总体是否通过
                "blocked": bool,       # 是否应阻塞合并
                "message": str,        # 结果描述
                "comparison": {...},   # baseline 对比详情
            }
        """
        comparison = self.baseline.compare(current_report)

        # 没有 baseline → 通过，同时保存这个结果作为新的 baseline
        if not comparison["baseline_found"]:
            self.baseline.save(current_report)
            return {
                "passed": True,
                "blocked": False,
                "message": "首次评测，已保存为 baseline",
                "comparison": comparison,
            }

        blocked = False
        reasons = []

        # 1. 总体质量下降检查
        if comparison["regression_detected"]:
            blocked = True
            reasons.append(
                f"总体质量下降 {comparison['score_diff']:.3f} "
                f"(阈值: -{comparison['regression_gate_threshold']})"
            )

        # 2. 核心分类（rag, search）下降检查
        by_category = current_report.get("by_category", {})
        baseline_data = self.baseline.load_latest() or {}
        baseline_by_cat = baseline_data.get("by_category", {})

        for cat in CORE_CATEGORIES:
            new_cat_score = by_category.get(cat, {}).get("overall_score", 0)
            old_cat_score = baseline_by_cat.get(cat, {}).get("overall_score", 0)
            if old_cat_score > 0 and (new_cat_score - old_cat_score) < -CORE_THRESHOLD:
                blocked = True
                reasons.append(
                    f"核心分类 '{cat}' 质量下降: {new_cat_score:.3f} vs {old_cat_score:.3f}"
                )

        # 3. 新增失败检查
        new_failures = current_report.get("summary", {}).get("num_failed_steps", 0)
        old_failures = baseline_data.get("summary", {}).get("num_failed", 0)
        if new_failures > old_failures + 2:  # 允许 2 条浮动
            blocked = True
            reasons.append(f"新增失败步骤: {new_failures}（之前: {old_failures}）")

        # 结果组装
        message = "; ".join(reasons) if reasons else comparison["message"]

        return {
            "passed": not blocked,
            "blocked": blocked,
            "message": f"{'❌ 阻塞' if blocked else '✅ 通过'}: {message}",
            "reasons": reasons,
            "comparison": comparison,
            "threshold": self.threshold,
        }
