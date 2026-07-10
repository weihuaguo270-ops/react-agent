"""dynamic_rubric — 动态评分标准生成（核心创新）

传统的 eval 使用固定模板评分：
    "检查答案是否基于 context" → 对所有用例都一样

动态 Rubric 针对每步的实际上下文，让 Judge LLM 先理解"这一步在做什么"，
再基于当时环境生成针对性的评分标准：
    Step 3（Agent 调用了 web_search 搜索"Python SQL注入"）
    → 动态标准：
      ① 搜索词在当前任务下是否合理？
      ② 搜索结果是否被后续步骤利用？
      ③ 如果搜索效果不好，Agent 是否有备选方案？

设计思路：
    1. Agent 执行完一步（或完成全部轨迹后）
    2. 对该步构建"评分上下文"（输入/输出/当时可用信息）
    3. 让 Judge 先理解"这一步在整体任务中的角色"
    4. Judge 动态生成 2-4 条评分标准
    5. Judge 按自己生成的标准打分

    注：实际实现中，步骤 3-5 可以一次 LLM 调用完成（在 prompt 中
    植入"先理解再生成标准再打分"的指令）。此处提供分层 API
    也支持一次调用模式。
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Optional

from core.trajectory_parser import StepNode, StepsDAG


@dataclass
class DynamicRubric:
    """动态生成的评分标准

    属性:
        dimension:   评分维度（如 "faithfulness"、"tool_quality"）
        criteria:    评分标准描述（给 Judge 看）
        context:     该标准对应的上下文片段
    """
    dimension: str
    criteria: str
    context: str = ""


@dataclass
class StepEvaluationContext:
    """单步评分所需的完整上下文

    属性:
        query:             用户原始输入
        current_step:      当前要评分的步骤
        step_index:        当前步序号
        total_steps:       总步数
        tool_input:        如果是工具调用，工具输入
        tool_output:       如果是工具调用，工具返回
        previous_steps:    前几步（供 Judge 理解上下文）
        downstream_steps:  后几步（供 Judge 理解影响）
        dag_summary:       DAG 摘要（步骤类型分布、已用工具）
    """
    query: str
    current_step: StepNode
    step_index: int
    total_steps: int
    tool_input: Optional[dict] = None
    tool_output: Optional[str] = None
    previous_steps: list[dict] = field(default_factory=list)
    downstream_steps: list[dict] = field(default_factory=list)
    dag_summary: dict = field(default_factory=dict)


# ──────────────────────────────────────────────
# 动态评分标准生成
# ──────────────────────────────────────────────


def build_step_context(
    dag: StepsDAG,
    step_index: int,
) -> StepEvaluationContext:
    """为 DAG 中的某一步构建评分上下文

    参数:
        dag:         完整的 StepsDAG
        step_index:  要评分的步骤序号

    返回:
        StepEvaluationContext: 包含该步在整体任务中的位置信息
    """
    node = dag.get_node(step_index)
    if node is None:
        raise ValueError(f"步骤 {step_index} 在 DAG 中不存在")

    # 前几步（最多 3 步）
    prev_steps = []
    for i in range(max(0, step_index - 3), step_index):
        prev = dag.get_node(i)
        if prev:
            prev_steps.append({
                "step_index": prev.step_index,
                "type": prev.step_type,
                "content": prev.content[:200],
                "tool": prev.tool_name,
            })

    # 后几步（最多 2 步）
    next_steps = []
    for i in range(step_index + 1, min(dag.num_steps, step_index + 3)):
        next_node = dag.get_node(i)
        if next_node:
            next_steps.append({
                "step_index": next_node.step_index,
                "type": next_node.step_type,
                "content": next_node.content[:200] if next_node.content else "",
            })

    return StepEvaluationContext(
        query=dag.query,
        current_step=node,
        step_index=step_index,
        total_steps=dag.num_steps,
        tool_input=node.tool_args,
        tool_output=node.tool_result,
        previous_steps=prev_steps,
        downstream_steps=next_steps,
        dag_summary={
            "total_steps": dag.num_steps,
            "step_types": [n.step_type for n in dag.nodes],
            "tools_used": list(set(
                n.tool_name for n in dag.nodes if n.tool_name
            )),
        },
    )


def generate_rubrics_for_step(
    context: StepEvaluationContext,
) -> list[DynamicRubric]:
    """为某一步动态生成评分标准

    根据步骤类型（thought / action / observation / final）生成不同的标准。

    参数:
        context: 该步的评分上下文

    返回:
        list[DynamicRubric]: 2-4 条评分标准

    注意：
        这个方法返回的是可解释的标准列表，供开发者查看。
        实际评分时，Judge LLM 通常在一次调用中同时完成
        "理解→生成标准→打分"三步，以避免额外的 LLM 开销。
    """
    node = context.current_step
    rubrics: list[DynamicRubric] = []

    if node.step_type == "thought":
        rubrics = _rubrics_for_thought(context)
    elif node.step_type == "action":
        rubrics = _rubrics_for_action(context)
    elif node.step_type == "observation":
        rubrics = _rubrics_for_observation(context)
    elif node.step_type == "final":
        rubrics = _rubrics_for_final(context)

    return rubrics


def _rubrics_for_thought(context: StepEvaluationContext) -> list[DynamicRubric]:
    """thought 步骤的标准"""
    node = context.current_step
    return [
        DynamicRubric(
            dimension="reasoning_quality",
            criteria=(
                f"Agent 的推理步骤（Step {node.step_index}）是否合理？\n"
                f"  Agent 当时的想法：{node.content[:200]}\n"
                f"  前一步：{context.previous_steps[-1]['content'][:100] if context.previous_steps else '(无)'}\n\n"
                f"评分：1=完全不合理，3=基本合理但可优化，5=非常合理且高效"
            ),
            context=node.content,
        ),
        DynamicRubric(
            dimension="decision_correctness",
            criteria=(
                f"Agent 在当前上下文中是否做出了正确的决策？\n"
                f"  - 这个推理是否考虑了前序步骤的结果？\n"
                f"  - 推理方向是否与用户目标一致？\n"
                f"评分：1=偏离目标，3=基本正确，5=精准且高效"
            ),
        ),
    ]


def _rubrics_for_action(context: StepEvaluationContext) -> list[DynamicRubric]:
    """action 步骤的标准"""
    node = context.current_step
    tool_name = node.tool_name or "unknown"
    return [
        DynamicRubric(
            dimension="tool_selection",
            criteria=(
                f"Agent 在当前任务中选择了 {tool_name} 工具。\n"
                f"  任务背景：{context.query[:100]}\n"
                f"  工具参数：{node.tool_args}\n"
                f"  此时 Agent 已有信息：{context.previous_steps[-1]['content'][:100] if context.previous_steps else '(无)'}\n\n"
                f"这个工具在当前上下文中是否是最优选择？\n"
                f"评分：1=完全错误的工具，3=可用但非最优，5=最佳选择"
            ),
            context=str(node.tool_args),
        ),
        DynamicRubric(
            dimension="tool_argument_quality",
            criteria=(
                f"Agent 调用 {tool_name} 时的参数质量：\n"
                f"  - 参数是否完整？\n"
                f"  - 参数值是否基于前序步骤的结果？\n"
                f"  - 参数值是否合理（没有编造 ID 或关键词）？\n"
                f"  参数：{node.tool_args}\n"
                f"评分：1=编造参数，3=基本合理，5=精准无误"
            ),
            context=str(node.tool_args),
        ),
    ]


def _rubrics_for_observation(context: StepEvaluationContext) -> list[DynamicRubric]:
    """observation 步骤的标准"""
    node = context.current_step
    return [
        DynamicRubric(
            dimension="information_utilization",
            criteria=(
                f"Agent 如何处理工具返回的结果？\n"
                f"  工具返回：{node.content[:200]}\n"
                f"  - 是否正确解读了返回数据？\n"
                f"  - 是否识别了异常/空结果并做了相应处理？\n"
                f"评分：1=忽略结果，3=基本理解，5=精准利用并识别异常"
            ),
            context=node.content,
        ),
    ]


def _rubrics_for_final(context: StepEvaluationContext) -> list[DynamicRubric]:
    """final 步骤的标准"""
    node = context.current_step
    return [
        DynamicRubric(
            dimension="completeness",
            criteria=(
                f"Agent 的最终回答是否完整覆盖了用户需求？\n"
                f"  用户原始需求：{context.query}\n"
                f"  Agent 最终输出：{node.content[:300]}\n"
                f"评分：1=遗漏关键信息，3=覆盖大部分，5=全面且准确"
            ),
            context=node.content,
        ),
        DynamicRubric(
            dimension="context_faithfulness",
            criteria=(
                f"最终答案是否忠实地基于工具调用和检索结果？\n"
                f"  前序步骤的发现：{[s['content'][:100] for s in context.previous_steps[-2:]]}\n"
                f"  - 答案中是否有模型编造的信息？\n"
                f"  - 答案是否引用了实际获取的数据而非记忆？\n"
                f"评分：1=编造，3=部分基于实际信息，5=完全基于实际信息"
            ),
        ),
    ]


# ──────────────────────────────────────────────
# Judge Prompt 生成（一次调用模式）
# ──────────────────────────────────────────────


def build_step_judge_prompt(context: StepEvaluationContext) -> str:
    """为某一步生成完整的 Judge prompt

    这个 prompt 让 Judge 在一次调用中同时完成：
      1. 理解该步在整体任务中的角色
      2. 针对该步的实际情况生成评分标准
      3. 按照生成的标准打分

    参数:
        context: 该步的评分上下文

    返回:
        str: 可直接发给 Judge LLM 的 prompt
    """
    node = context.current_step
    prev_text = "\n".join(
        f"  Step {s['step_index']} [{s['type']}]: {s['content'][:150]}"
        for s in context.previous_steps
    ) or "  (首步)"
    next_text = "\n".join(
        f"  Step {s['step_index']} [{s['type']}]: {s['content'][:150]}"
        for s in context.downstream_steps
    ) or "  (末步)"

    return f"""你是一个 Agent 执行质量评估器。请评估 Agent 在以下步骤中的表现。

## 任务背景
用户原始需求: {context.query}

## 当前步骤（Step {node.step_index}/{context.total_steps - 1}）
类型: {node.step_type}
内容: {node.content[:300]}
{f"调用的工具: {node.tool_name}" if node.tool_name else ""}
{f"工具参数: {node.tool_args}" if node.tool_args else ""}

## 前序步骤（上下文）
{prev_text}

## 后续步骤（影响）
{next_text}

## 你的任务
1. 首先理解：这一步在整体任务中扮演什么角色？
2. 然后针对这一步的实际情况，自动生成 2-4 条评分标准
3. 最后按你生成的标准逐条打分

输出 JSON 格式（不要附加其他文本）：
{{
    "role_understanding": "这一步在整体任务中的角色",
    "rubrics": [
        {{"dimension": "维度名", "criteria": "评分标准描述", "score": <1-5>, "reason": "评分理由"}},
        ...
    ],
    "step_score": <所有 rubric 的平均分>,
    "needs_revision": true/false
}}

规则：
- needs_revision = true 当有任何 rubric 得分 <= 3
- 评分要严格：4 分 = 好，5 分 = 非常好，3 分 = 还行但可优化
- 如果参数看起来像编造的（不存在的 ID、日期等），给低分
- 如果这一步的结果被后续步骤忽略或误用，考虑扣分
"""


def build_trajectory_judge_prompt(dag: StepsDAG) -> str:
    """为整条轨迹生成整体评估 prompt

    用于快速整体评估，不逐步骤深入评分。
    """
    steps_text = []
    for node in dag.nodes:
        if node.tool_name:
            steps_text.append(
                f"  Step {node.step_index} [{node.step_type}]: "
                f"调用 {node.tool_name}({node.tool_args}) → {node.tool_result[:100] if node.tool_result else ''}"
            )
        else:
            steps_text.append(
                f"  Step {node.step_index} [{node.step_type}]: "
                f"{node.content[:150]}"
            )

    return f"""你是一个 Agent 执行质量评估器。请整体评估以下 Agent 的执行轨迹。

## 用户需求
{dag.query}

## 最终答案
{dag.final_answer[:500]}

## 执行轨迹（共 {dag.num_steps} 步）
{chr(10).join(steps_text)}

## 评估
请从以下维度评估（1-5分）：
1. **整体质量**：最终答案是否满足用户需求？
2. **路径效率**：Agent 是否走了不必要的弯路？
3. **工具利用**：Agent 是否正确选择了工具并合理使用了结果？

输出 JSON：
{{
    "overall_score": <1-5>,
    "efficiency_score": <1-5>,
    "tool_usage_score": <1-5>,
    "strengths": ["优点1", "优点2"],
    "weaknesses": ["缺点1", "缺点2"],
    "needs_revision": true/false
}}
"""
