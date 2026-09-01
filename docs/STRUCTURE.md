# 仓库结构

Core 运行时、**两条企业业务线、跨域 benchmark 与共享评测能力层**、评测与实验模块的分区说明。应用地图：[`APPLICATION_DIRECTION.md`](APPLICATION_DIRECTION.md)。

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
├── skills/                业务 Skill 契约、确定性路由和结果验证
├── workflow/              声明式 Workflow
├── apps/docs_troubleshoot/  业务线② · 技术支持/工单辅助 · 证据化文档排障
├── apps/security_triage/    安全垂直 MVP · 公开情报研判与人工复核
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
| 业务 Skill / 场景路由 | `src/react_agent/skills/` |
| 语料 / 黄金集 / 产品定位 | `apps/docs_troubleshoot/` · [`EVIDENCE_DOCS_TROUBLESHOOT.md`](EVIDENCE_DOCS_TROUBLESHOOT.md) |
| 安全研判 MVP | `apps/security_triage/` · [`SECURITY_TRIAGE_AGENT.md`](SECURITY_TRIAGE_AGENT.md) |
| 安全研判评测 / 回放 | `examples/eval/run_security_triage_eval.py` · `examples/fixtures/security_triage_goldens.json` |
| HTTP 服务面 | `src/react_agent/server/` |
| 权限表 | `src/react_agent/safety/permissions.py` |
| 垂类 Demo | `examples/demos/` |
| 黄金集评测脚本 | `examples/eval/run_docs_troubleshoot_eval.py` · [`DOCS_TROUBLESHOOT_EVAL.md`](DOCS_TROUBLESHOOT_EVAL.md) |
| 公开 RAG / capability | `examples/eval/` · [`EVAL_INDEX.md`](EVAL_INDEX.md) |
| 成熟度与范围 | [`PRODUCTION_MATURITY.md`](PRODUCTION_MATURITY.md) |
| LangGraph 对照 | `experiments/langgraph/` |

## 阅读顺序

1. 本页（结构）
2. [`APPLICATION_DIRECTION.md`](APPLICATION_DIRECTION.md)（两条业务线 + benchmark + 共享能力入口）
3. [`CORE_ARCHITECTURE.md`](CORE_ARCHITECTURE.md)（控制流）
4. [`AGENT_WORKFLOW.md`](AGENT_WORKFLOW.md)（主路径用法）
5. [`EVAL_INDEX.md`](EVAL_INDEX.md)（评测索引；报告正文在 `reports/`）
6. [`EVIDENCE_DOCS_TROUBLESHOOT.md`](EVIDENCE_DOCS_TROUBLESHOOT.md)（垂直 demo 边界）
7. [`EXPERIMENTAL.md`](EXPERIMENTAL.md)（可选能力）
