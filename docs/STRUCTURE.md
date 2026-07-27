# 仓库结构

Core 运行时、主场景、评测与实验模块的分区说明。包内模块见 [`src/react_agent/README.md`](../src/react_agent/README.md)。

## 顶层目录

| 路径 | 职责 |
|------|------|
| `src/react_agent/` | 可安装运行时（Core + 可选实验模块） |
| `examples/demos/` | 演示脚本（见 `examples/README.md`） |
| `examples/eval/` | 回归、公开基准与快照发布 |
| `docs/` | 架构与导航；日期报告在 `docs/reports/`；JSON 在 `docs/snapshots/` |
| `experiments/langgraph/` | LangGraph 对照实现（可选依赖） |
| `schemas/` | 跨仓轨迹契约（Format B） |
| `fixtures/` | 离线语料等固定夹具 |
| `tests/` | pytest |
| `__main__.py` / `react_cli.py` | CLI shim（`python -m react_agent` / 根入口） |

## Core 路径

```
src/react_agent/
├── react_loop.py          ReAct 循环
├── workflow/              声明式 Workflow
├── apps/docs_troubleshoot/  主场景：证据化文档排障（见 EVIDENCE_DOCS_TROUBLESHOOT.md）
├── server/                HTTP：/health /v1/chat /v1/workflows
├── tools/                 工具注册表
├── safety/                权限闸门 + HITL
├── harness/               轨迹录制 / 回放 / 沙箱超时
├── resilience.py          ToolGuard
├── llm.py · prompts.py · context.py · memory.py · cot.py
└── eval/                  capability / execution / public* 评测
```

## 实验模块

默认不进入 Core 工具表。清单见 [`EXPERIMENTAL.md`](EXPERIMENTAL.md)：`rag.py`、`mcp_*.py`、`orchestrator.py`、`planner.py`、`tot.py`、`dashboard/`。

## 变更入口

| 目标 | 位置 |
|------|------|
| 声明式流水线 / builtins | `src/react_agent/workflow/` |
| 语料 / 黄金集 / 产品定位 | `apps/docs_troubleshoot/` · [`EVIDENCE_DOCS_TROUBLESHOOT.md`](EVIDENCE_DOCS_TROUBLESHOOT.md) |
| HTTP 服务面 | `src/react_agent/server/` |
| 权限表 | `src/react_agent/safety/permissions.py` |
| 垂类 Demo | `examples/demos/` |
| 黄金集评测脚本 | `examples/eval/run_docs_troubleshoot_eval.py` · [`DOCS_TROUBLESHOOT_EVAL.md`](DOCS_TROUBLESHOOT_EVAL.md) |
| 公开 RAG / capability | `examples/eval/` · [`EVAL_INDEX.md`](EVAL_INDEX.md) |
| 成熟度与范围 | [`PRODUCTION_MATURITY.md`](PRODUCTION_MATURITY.md) |
| LangGraph 对照 | `experiments/langgraph/` |

## 阅读顺序

1. 本页（结构）
2. [`CORE_ARCHITECTURE.md`](CORE_ARCHITECTURE.md)（控制流）
3. [`AGENT_WORKFLOW.md`](AGENT_WORKFLOW.md)（主路径用法）
4. [`EVAL_INDEX.md`](EVAL_INDEX.md)（评测索引；报告正文在 `reports/`）
5. [`EVIDENCE_DOCS_TROUBLESHOOT.md`](EVIDENCE_DOCS_TROUBLESHOOT.md)（主场景定位与路线图）
6. [`EXPERIMENTAL.md`](EXPERIMENTAL.md)（可选能力）
