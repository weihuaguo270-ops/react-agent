# Core 架构

结构地图：[`STRUCTURE.md`](STRUCTURE.md)。主场景说明：[`EVIDENCE_DOCS_TROUBLESHOOT.md`](EVIDENCE_DOCS_TROUBLESHOOT.md)。

运行时走 **自建 Core**（轻量 ReAct + 领域工具 + HTTP），**不以 LangGraph / 图编排为默认或评判标准**。主场景 **docs_troubleshoot** 默认 **离线 Agent 循环**（观测驱动选工具 + `verify_citations` + Harness 轨迹）；Live 为 `react_loop` + LLM；固定 DAG Workflow 为 legacy 对照。

## 与主流 Agent 的对齐（实践共性）

生产里常见的 Agent 服务形态大致如下；本项目 **整体骨架对齐**，差异在循环内的治理细节（见下一节）。

| 层 | 主流做法 | 本项目 |
|----|----------|--------|
| 交互 | HTTP Chat API、JSON | `/v1/chat`、`/v1/info`、Docker |
| 推理 | LLM + function calling（ReAct 形） | `react_loop`（Live）；`agent_runner`（离线同构） |
| 知识 | RAG / 文档检索 | `search_docs`、`lookup_api` |
| 工具 | 领域工具 + 通用工具 | docs 工具集 + ToolGuard |
| 安全 | 拒答、权限、危险操作拦截 | policy + permission gate + `fix_steps` 分级 |
| 可观测 | 日志、request_id、（部分）轨迹 | Format B 轨迹 + StepWatcher（可选） |
| 质量 | 回归集 / smoke | 四套 eval + CI（**验收手段**，非产品卖点） |
| 交付 | 单服务、health/ready | `/health`、`/ready`、compose |

**刻意不作为 KPI 的能力**：复杂图编排、Checkpoint 中断恢复、多租户平台——多数 Runbook/Copilot 类 Agent 也不会先做这些。

## 细节优化（相对主流的加分项）

在 ReAct 循环与主场景契约上，做了运行时级处理（不只靠 prompt）：

| 细节 | 主流常见 | 本项目 |
|------|----------|--------|
| 工具失败 | 直接返回 error | **Harness 自修提示** + ToolGuard 分级重试/熔断 |
| 重复调用 | 靠 prompt | **Runtime 拦截** 相邻同参 duplicate |
| 步数耗尽 | 常无答案 | **reserve_final_step** + 强制 FINAL ANSWER |
| 文档问答 | RAG 后直接生成 | **强制 `verify_citations` 工具步** |
| 修复建议 | 模型自由输出 | **fix_steps**：deny → ask → allow |
| 迭代 | 改 prompt | **轨迹 → StepWatcher → failure flywheel → 改 loop** |

## 分层

```
Apps (docs_troubleshoot)     ← Agent 循环（默认）+ legacy Workflow + diagnosis
  → agent_runner（观测 → 工具 → verify_citations → policy）
  → Workflow v5（固定 DAG，REACT_AGENT_DOCS_ENGINE=workflow）
  → react_loop（LLM ReAct；Live）
  → Tools + Permission gate + ToolGuard
  → Harness Format B / Eval（验收，非卖点）
  → Server HTTP + 产品 UI
```

## Agent 循环（默认实现）

**离线 Agent 路径**（`agent_runner.py`）：

1. 根据 state / 观测 **选择下一工具**（非固定顺序 DAG）
2. 调用 `search_docs` / `lookup_api` / 现场证据 parse / `fetch_trace` 等
3. 合成 draft 后 **必须** 调用 `verify_citations` 工具步
4. `enforce_answer_policy` + `build_diagnosis`
5. 全程 `start_trajectory` → Format B 步记录 → `finish_trajectory`

Live：`REACT_AGENT_SERVER_LLM=1` 时 `/v1/chat` 走 `react_loop`，同一套 docs 工具与 prompt。

## Workflow（legacy DAG）

v5 固定路径：**现场证据 → 检索 → synthesize → policy → diagnosis**（`REACT_AGENT_DOCS_ENGINE=workflow`）。用于对照与回归，不是默认叙事中心。

```bash
python -m react_agent.workflow run docs_troubleshoot --query "401 怎么返回？"
python examples/eval/run_docs_troubleshoot_eval.py          # 默认 agent 路径
```

## 实验对照（可选）

`experiments/langgraph/` 为 **可选** 图编排对照（`pip install -e ".[langgraph]"`），不参与主场景交付与成熟度评判。见 [`EXPERIMENTAL.md`](EXPERIMENTAL.md)。

## 设计原则

1. **整体贴近主流 ReAct 服务**；**细节**在循环治理与领域工具契约上加深  
2. 主场景默认 Agent 循环；Workflow DAG 保留作 legacy / 对照  
3. eval 验证 Agent 边界，不作为对外产品叙事中心  
4. P1 优先补齐主流交付项：Bearer 鉴权、结构化 JSON 日志、**verify_actions 接工具执行**
