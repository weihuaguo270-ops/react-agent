# Core 自建架构（主路径）

结构地图：[`STRUCTURE.md`](STRUCTURE.md)。

本仓默认叙事以 **自建 Core** 为准；LangGraph 仅作可选对照，不参与主路径依赖与默认演示。

## 分层

```
Apps (docs_troubleshoot)
  → Workflow（确定性多步流水线）
  → react_loop（自由 ReAct，可选）
  → Tools + Permission gate + ToolGuard
  → Harness Format B / Eval
  → Server HTTP
```

## Workflow（主路径）

声明式步骤：`tool` / `policy` / `final`，共享 state，可审计 step 记录。

```bash
python -m react_agent.workflow list
python -m react_agent.workflow run docs_troubleshoot --query "401 怎么返回？"
python examples/demos/demo_workflow.py
python examples/eval/run_docs_troubleshoot_eval.py   # 严格黄金集：Workflow + 无泄漏
```

Agent 工具：`list_workflows` / `run_workflow`（默认注册）。

HTTP：`GET /v1/workflows`，`POST /v1/workflows/run`。

设计参考（学模式不搬仓）：CrewAI Flows 的确定性编排与条件路由、OpenHands Skills 的「场景知识包」——本仓用 Workflow + `apps/` 垂直后端落地。

Workflow 优化点：
- 注册时 `validate_workflow`（环检测 / 缺 handler）
- `when=` 软跳过（条件路由轻量版）
- `WorkflowResult.to_trajectory()` 对齐 Format B 证据链
- 工具面默认注册 `list_workflows` / `run_workflow`
- 黄金集：只评最终 answer；禁止 must_* 注入检索；含 hard / refuse 标签

## 与 LangGraph

| | Core | LangGraph (`experiments/`) |
|--|------|----------------------------|
| 默认 | 是 | 否 |
| 依赖 | 无框架 | 可选 `[langgraph]` |
| 用途 | 主场景 / 评测 / HTTP | 图编排对照学习 |

## 优化原则

1. 主场景走 Workflow（可控）或 ReAct（探索），不要默认上多 Agent  
2. 工具表 + 权限表集中扩展  
3. 每条流水线可离线回归（黄金集 / workflow steps）
