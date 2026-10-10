# 仓库结构

Core 运行时、**三类主流应用**、评测与实验模块的分区说明。应用地图：[`APPLICATION_DIRECTION.md`](APPLICATION_DIRECTION.md)。

## 顶层目录

| 路径 | 职责 |
|------|------|
| `src/react_agent/` | 可安装运行时（Core + 可选实验模块） |
| `demos/` | 产品/能力演示（见 `demos/README.md`） |
| `scripts/eval/` | 评测/回归/验收/冒烟入口（按子目录细分，见 `scripts/eval/README.md`） |
| `docs/` | 架构与导航；日期报告在 `docs/reports/`；JSON 在 `docs/snapshots/` |
| `schemas/` | 跨仓轨迹契约（Format B） |
| `fixtures/` | 语料与评测夹具（`expense/` · docs_troubleshoot · harness / software_tasks 等） |
| `tests/` | pytest |
| `__main__.py` / `react_cli.py` | CLI shim（`python -m react_agent` / 根入口） |

## Core 路径

```
src/react_agent/
├── react_loop.py          ReAct 循环
├── workflow/              声明式 Workflow
├── apps/docs_troubleshoot/  垂直 demo：② 客服线 · 证据化文档排障
├── server/                HTTP：stdlib app + FastAPI fastapi_app（两个入口点）
├── skills/                可注册 skill：schema 校验 / 业务边界 / 风险评估 · run_skill()
├── multimodal.py          本地制品归一化为可审计证据（不调用 OCR/VLM 服务）
├── tools/                 工具注册表
├── tool_scope.py          Worker 工具面声明（ToolScope；不触发 tools 包装配）
├── write_sets.py          写集冲突判定（并行写安全依赖它）
├── orchestrator.py        多 Agent 编排（Orchestrator / Worker）
├── planner.py             任务分解 + 依赖/写集分层
├── safety/                权限闸门 + HITL
├── harness/               轨迹录制 / 回放 / 沙箱超时
├── resilience.py          ToolGuard
├── llm.py · prompts.py · context.py · memory.py · cot.py
└── eval/                  capability / execution / public* 评测
```

## 实验模块

默认不进入 Core 工具表。清单见 [`EXPERIMENTAL.md`](EXPERIMENTAL.md)：`rag.py`、`mcp_*.py`、`tot.py`、`dashboard/`。

多 Agent 编排（`orchestrator.py` / `planner.py` / `tool_scope.py` / `write_sets.py`）同样不在 Core 工具表内，但已具备声明式工具面、写冲突分层与深度/并发上限；能力边界见 [`CORE_ARCHITECTURE.md`](CORE_ARCHITECTURE.md)。**注意并行 Worker 无工作区隔离。**

## 变更入口

| 目标 | 位置 |
|------|------|
| 声明式流水线 / builtins | `src/react_agent/workflow/` |
| 语料 / 黄金集 / 产品定位 | `apps/docs_troubleshoot/` · [`EVIDENCE_DOCS_TROUBLESHOOT.md`](EVIDENCE_DOCS_TROUBLESHOOT.md) |
| expense Workflow + 决策 | `apps/expense/` · `fixtures/expense/` · [`spec/EXPENSE_WORKFLOW_DECISION_SPEC.md`](spec/EXPENSE_WORKFLOW_DECISION_SPEC.md) |
| HTTP 服务面 | `src/react_agent/server/` |
| 权限表 | `src/react_agent/safety/permissions.py` |
| 垂类 Demo | `demos/` |
| 黄金集评测脚本 | `scripts/eval/docs/run_docs_troubleshoot_eval.py` · [`DOCS_TROUBLESHOOT_EVAL.md`](DOCS_TROUBLESHOOT_EVAL.md) |
| 公开 RAG / capability | `scripts/eval/` · [`EVAL_INDEX.md`](EVAL_INDEX.md) |
| 成熟度与范围 | [`PRODUCTION_MATURITY.md`](PRODUCTION_MATURITY.md) |

## 阅读顺序

1. 本页（结构）
2. [`APPLICATION_DIRECTION.md`](APPLICATION_DIRECTION.md)（三类主流应用 + 入口）
3. [`CORE_ARCHITECTURE.md`](CORE_ARCHITECTURE.md)（控制流）
4. [`AGENT_WORKFLOW.md`](AGENT_WORKFLOW.md)（主路径用法）
5. [`EVAL_INDEX.md`](EVAL_INDEX.md)（评测索引；报告正文在 `reports/`）
6. [`EVIDENCE_DOCS_TROUBLESHOOT.md`](EVIDENCE_DOCS_TROUBLESHOOT.md)（垂直 demo 边界）
7. [`EXPERIMENTAL.md`](EXPERIMENTAL.md)（可选能力）
