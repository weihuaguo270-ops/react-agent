# Runbook：轨迹与复盘

- 默认导出 Format B（路径：`schemas/harness_trajectory.schema.json`）
- 失败分类交给 trace-debugger；过程奖励交给 llm-eval-engine
- 相邻完全相同工具调用默认拦截（`REACT_AGENT_BLOCK_DUPLICATE_TOOLS`）
