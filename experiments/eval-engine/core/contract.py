"""contract — Verifier 契约接口定义

Verifier Contract 是整个 eval-engine 的基础抽象。
每一个 verifier 是一份"评分契约"，包含：
  - name:       契约名称
  - rubric:     评分标准（字符串，可作为 LLM prompt 的一部分）
  - min_score:  最低可接受分数（低于此触发修正）
  - weight:     在最终总分中的权重

用法：
    from core.contract import VerifierContract

    faithfulness = VerifierContract(
        name="faithfulness",
        rubric="检查答案是否基于提供的 context。1=完全编造，5=完全基于 context",
        min_score=4,
        weight=2.0,
    )
"""

from __future__ import annotations
from typing import Any


class VerifierContract:
    """Verifier 契约 — 一份可组合的评分标准

    每个契约定义了一个独立的评分维度，
    多个契约可以组合成一套评估体系。

    属性:
        name:      契约名称（唯一标识）
        rubric:    评分标准描述（供 Judge LLM 使用的 prompt）
        min_score: 最低可接受分数 [0, max_score]
        max_score: 最高分数
        weight:    权重（多维度加权时使用）
    """

    def __init__(
        self,
        name: str,
        rubric: str,
        min_score: float = 4.0,
        max_score: float = 5.0,
        weight: float = 1.0,
    ) -> None:
        """初始化契约

        参数:
            name:      契约名称，如 "faithfulness"、"tool_selection"
            rubric:    评分标准描述，如 "1=完全编造、5=完全基于 context"
            min_score: 最低可接受分数（低于此值停止循环并触发修正）
            max_score: 最高分数（默认 5 分制）
            weight:    加权时的权重（默认 1.0，不区分）
        """
        self.name = name
        self.rubric = rubric
        self.min_score = min_score
        self.max_score = max_score
        self.weight = weight

    def passed(self, score: float) -> bool:
        """当前分数是否通过该契约的阈值"""
        return score >= self.min_score

    def to_judge_prompt(self, context: dict[str, Any]) -> str:
        """生成 Judge LLM 的评分 prompt

        参数:
            context: 评分所需的上下文（含用户输入、Agent 输出、工具调用等）

        返回:
            str: 可直接发送给 Judge LLM 的 prompt
        """
        return f"""请根据以下标准评分：

评分标准（{self.name}）：
{self.rubric}

评分上下文：
{self._format_context(context)}

请输出 JSON 格式：
{{"score": <分数>, "reason": "<评分理由>"}}
"""

    def _format_context(self, context: dict[str, Any]) -> str:
        """格式化评分上下文"""
        parts = []
        for key, value in context.items():
            parts.append(f"[{key}]\n{value}")
        return "\n\n".join(parts)

    def __repr__(self) -> str:
        return (
            f"VerifierContract("
            f"name={self.name!r}, "
            f"min_score={self.min_score}, "
            f"max_score={self.max_score}, "
            f"weight={self.weight})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, VerifierContract):
            return NotImplemented
        return self.name == other.name
