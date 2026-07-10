"""trajectory_parser — Agent 执行轨迹 → DAG 步骤结构

核心功能：
    将 Agent 运行的原始轨迹（trajectory JSON）解析为可逐步骤评分的
    DAG（有向无环图）结构。

DAG 中的每个节点（StepNode）代表 Agent 的一次动作：
  - 一次工具调用 + 结果
  - 一次 LLM 推理 + 输出
  - 一次决策（分支/合并）

DAG 中的每条边（StepEdge）代表步骤间的依赖关系：
  - 输出 → 输入的数据流动
  - 前序 → 后继的控制流

输入格式（与 src/handwritten_react_agent 兼容）：
    {
        "session_id": "traj_xxx",
        "steps": [
            {
                "step_index": 0,
                "type": "thought" | "action" | "observation" | "final",
                "content": "...",
                "action": {"name": "web_search", "args": {...}},
                "observation": "...",
                "timestamp": 1234567890.0,
            },
            ...
        ],
        "total_steps": 5,
        "total_tokens_estimated": 1200,
        "final_answer": "...",
    }

输出 DAG 结构：
    StepsDAG:
        nodes: [StepNode, ...]
        edges: [StepEdge, ...]
"""

from __future__ import annotations
import json
from dataclasses import dataclass, field
from typing import Optional


# ──────────────────────────────────────────────
# 数据模型
# ──────────────────────────────────────────────


@dataclass
class StepNode:
    """DAG 中的一个步骤节点

    属性:
        step_index:  步骤序号（0-based）
        step_type:   类型: thought / action / observation / final
        content:     步骤的文本内容（LLM 推理或工具返回）
        tool_name:   如果是工具调用，工具名
        tool_args:   如果是工具调用，参数字典
        tool_result: 如果是工具调用，调用结果
        score:       该步骤的 Process Reward 评分（None 表示未评）
        score_reason:评分理由
        metadata:    其他元数据（timestamp 等）
    """
    step_index: int
    step_type: str  # "thought" | "action" | "observation" | "final"
    content: str = ""
    tool_name: Optional[str] = None
    tool_args: Optional[dict] = None
    tool_result: Optional[str] = None
    score: Optional[float] = None
    score_reason: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class StepEdge:
    """DAG 中的依赖边

    属性:
        from_index: 上游步骤序号
        to_index:   下游步骤序号
        relation:   依赖类型:
            "output_to_input"  — 上游输出是下游的输入
            "control_flow"     — 上游完成 → 下游开始
            "error_propagate"  — 上游失败 → 下游受波及
    """
    from_index: int
    to_index: int
    relation: str = "control_flow"


@dataclass
class StepsDAG:
    """完整的 DAG 结构

    属性:
        nodes:      所有步骤节点
        edges:      所有依赖边
        query:      原始用户输入
        final_answer: 最终答案
        metadata:   元数据（session_id、tokens 等）
    """
    nodes: list[StepNode] = field(default_factory=list)
    edges: list[StepEdge] = field(default_factory=list)
    query: str = ""
    final_answer: str = ""
    metadata: dict = field(default_factory=dict)

    @property
    def num_steps(self) -> int:
        return len(self.nodes)

    def get_node(self, step_index: int) -> Optional[StepNode]:
        """按索引获取步骤节点"""
        for node in self.nodes:
            if node.step_index == step_index:
                return node
        return None

    def get_downstream(self, step_index: int) -> list[StepNode]:
        """获取某步骤的全部下游节点（受它影响的步骤）"""
        downstream_indices = {
            e.to_index for e in self.edges if e.from_index == step_index
        }
        return [n for n in self.nodes if n.step_index in downstream_indices]

    def get_upstream(self, step_index: int) -> list[StepNode]:
        """获取某步骤的全部上游节点（影响它的步骤）"""
        upstream_indices = {
            e.from_index for e in self.edges if e.to_index == step_index
        }
        return [n for n in self.nodes if n.step_index in upstream_indices]

    def find_error_sources(self, threshold: float = 3.0) -> list[StepNode]:
        """定位低分 / 失败步骤中的根因节点

        根因定义：得分低于 threshold 但上游没有其他低于 threshold 的节点 → 错误源头在此。

        参数:
            threshold: 低分阈值（评分制 1-5，默认 3.0）
        """
        low_score_nodes = [
            n for n in self.nodes
            if n.score is not None and n.score < threshold
        ]
        error_sources = []
        for node in low_score_nodes:
            upstream = self.get_upstream(node.step_index)
            upstream_low = [
                u for u in upstream
                if u.score is not None and u.score < 0.6
            ]
            if not upstream_low:
                error_sources.append(node)
        return error_sources


# ──────────────────────────────────────────────
# 解析器
# ──────────────────────────────────────────────


def parse_trajectory(trajectory: dict) -> StepsDAG:
    """将 Agent 原始轨迹 JSON 解析为 StepsDAG

    支持两种轨迹格式：
      Format A（新格式，由 build_step_judge_prompt 等生成）：
          {"step_index": 0, "type": "thought", "content": "...", "action": {...}}
      Format B（现有 recorder 格式）：
          {"step": 1, "thought": "", "action": {"name": "...", "arguments": "..."}, "observation": "..."}

    参数:
        trajectory: 轨迹字典

    返回:
        StepsDAG: 可用于逐步骤评分的有向图结构

    异常:
        ValueError: 轨迹格式无法解析
    """
    if not trajectory:
        raise ValueError("轨迹数据无效：空字典")

    raw_steps = trajectory.get("steps", [])
    if not raw_steps:
        raise ValueError("轨迹数据无效：缺少 'steps' 字段或为空")

    dag = StepsDAG(
        query=trajectory.get("query", ""),
        final_answer=trajectory.get("final_answer", ""),
        metadata={
            "session_id": trajectory.get("session_id", ""),
            "model": trajectory.get("model", ""),
            "total_tokens_estimated": trajectory.get("total_tokens_estimated", 0),
        },
    )

    for raw_step in raw_steps:
        # 兼容两种格式：Format B 用 step，Format A 用 step_index
        step_index = raw_step.get("step_index")
        if step_index is None:
            step_index = raw_step.get("step", len(dag.nodes)) - 1  # 1-based → 0-based

        # 步骤类型推导
        if "type" in raw_step and raw_step["type"]:
            step_type = raw_step["type"]
        else:
            step_type = _infer_step_type(raw_step)

        # 动作/工具信息
        action_data = raw_step.get("action", {}) or {}
        if isinstance(action_data, dict):
            tool_name = action_data.get("name")
            # Format A 用 args，Format B 用 arguments
            tool_args = action_data.get("args") or action_data.get("arguments")
            # 如果 arguments 是 JSON 字符串，尝试解析
            if isinstance(tool_args, str):
                try:
                    tool_args = json.loads(tool_args)
                except (json.JSONDecodeError, TypeError):
                    pass
        else:
            tool_name = None
            tool_args = None

        # 内容提取
        content = (
            raw_step.get("content")
            or raw_step.get("observation")
            or raw_step.get("thought", "")
            or str(action_data)
        )

        # 观察结果
        observation = raw_step.get("observation") or raw_step.get("tool_result", "")

        node = StepNode(
            step_index=step_index,
            step_type=step_type,
            content=content,
            tool_name=tool_name,
            tool_args=tool_args,
            tool_result=observation or content,
            metadata={
                "timestamp": raw_step.get("timestamp", 0),
                "duration_seconds": raw_step.get("duration_seconds", 0),
                "tokens_estimated": raw_step.get("tokens_estimated", 0),
            },
        )
        dag.nodes.append(node)

    # 按 step_index 排序，确保顺序正确
    dag.nodes.sort(key=lambda n: n.step_index)

    # 自动构建依赖边
    _build_edges(dag)

    return dag


def _infer_step_type(raw_step: dict) -> str:
    """从步骤数据中推导步骤类型（兼容 Format B）

    规则：
      - 有 action 字段 → "action"
      - thought 含 "FINAL ANSWER" → "final"
      - 有 observation → "observation"
      - 否则 → "thought"
    """
    thought = raw_step.get("thought", "")
    if raw_step.get("action"):
        return "action"
    if "FINAL ANSWER" in thought.upper():
        return "final"
    if raw_step.get("observation"):
        return "observation"
    if thought.strip():
        return "thought"
    # 空 content 的步骤（最后一个 thought 步骤通常会是空的因为 FINAL ANSWER 在 content 里）
    return "thought"


def _build_edges(dag: StepsDAG) -> None:
    """根据步骤类型自动构建 DAG 依赖边

    规则：
      - 连续步骤默认 control_flow 依赖
      - action → observation 数据依赖
      - thought → action 推理依赖
    """
    for i, node in enumerate(dag.nodes):
        if i == 0:
            continue
        prev = dag.nodes[i - 1]

        # 默认控制流：前一步完成 → 后一步开始
        dag.edges.append(StepEdge(
            from_index=prev.step_index,
            to_index=node.step_index,
            relation="control_flow",
        ))

        # 数据依赖：action → observation
        if node.step_type == "observation" and prev.step_type in ("thought", "action"):
            dag.edges.append(StepEdge(
                from_index=prev.step_index,
                to_index=node.step_index,
                relation="output_to_input",
            ))


# ──────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────


def dag_to_text(dag: StepsDAG) -> str:
    """将 DAG 格式化为可读文本（供 Judge LLM 使用）

    返回:
        字符串，每步一行的文本描述
    """
    lines = [f"用户输入: {dag.query}", ""]
    for node in dag.nodes:
        prefix = f"Step {node.step_index} [{node.step_type}]"
        if node.tool_name:
            lines.append(f"  {prefix} 调用工具: {node.tool_name}({node.tool_args})")
        elif node.content:
            content_short = node.content[:120].replace("\n", " ")
            lines.append(f"  {prefix} {content_short}")
        else:
            lines.append(f"  {prefix}")
    if dag.final_answer:
        lines.append(f"  最终答案: {dag.final_answer[:200]}")
    return "\n".join(lines)


def dag_summary(dag: StepsDAG) -> dict:
    """生成 DAG 摘要统计"""
    types = {}
    for node in dag.nodes:
        types[node.step_type] = types.get(node.step_type, 0) + 1
    tools = [n.tool_name for n in dag.nodes if n.tool_name]
    scored = [n for n in dag.nodes if n.score is not None]
    avg_score = sum(n.score for n in scored) / len(scored) if scored else 0.0

    return {
        "total_steps": dag.num_steps,
        "step_types": types,
        "tools_used": tools,
        "scored_steps": len(scored),
        "avg_step_score": round(avg_score, 3),
        "error_sources": [n.step_index for n in dag.find_error_sources()],
    }
