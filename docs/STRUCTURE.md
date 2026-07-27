# 仓库结构地图

一眼分清：**Core（默认）** / **主场景** / **评测** / **实验**。包内细节见 [`src/react_agent/README.md`](../src/react_agent/README.md)。

## 顶层目录

| 路径 | 职责 |
|------|------|
| `src/react_agent/` | 可安装运行时（Core + 可选实验模块） |
| `examples/demos/` | 无评测门槛的演示脚本（见 `examples/README.md`） |
| `examples/eval/` | 回归 / 公开基准 / 发布快照 |
| `docs/` | 架构与导航；日期报告在 `docs/reports/`；JSON 在 `docs/snapshots/` |
| `experiments/langgraph/` | LangGraph 对照（非默认依赖） |
| `schemas/` | 跨仓轨迹契约（Format B） |
| `fixtures/` | 离线语料等固定夹具 |
| `tests/` | pytest |
| `__main__.py` / `react_cli.py` | CLI shim（`python -m react_agent` / 根入口） |

## Core 默认路径（生产向主叙事）

```
src/react_agent/
├── react_loop.py          ReAct 循环
├── workflow/              声明式 Workflow
├── apps/docs_troubleshoot/  主场景（语料 / 工具 / 严格黄金集）
├── server/                HTTP：/health /v1/chat /v1/workflows
├── tools/                 工具注册表
├── safety/                权限闸门 + HITL
├── harness/               轨迹录制 / 回放 / 沙箱超时
├── resilience.py          ToolGuard
├── llm.py · prompts.py · context.py · memory.py · cot.py
└── eval/                  评测 runner（capability / execution / public*）
```

## 实验模块（默认不进工具表）

见 [`EXPERIMENTAL.md`](EXPERIMENTAL.md)。典型：`rag.py`、`mcp_*.py`、`orchestrator.py`、`planner.py`、`tot.py`、`dashboard/`。

## 我想改 X → 去哪

| 目标 | 位置 |
|------|------|
| 声明式流水线 / builtins | `src/react_agent/workflow/` |
| 排障语料与黄金集 | `apps/docs_troubleshoot/corpus/` · `golden.json` · `eval_golden.py` |
| HTTP 服务面 | `src/react_agent/server/` |
| 权限表 | `src/react_agent/safety/permissions.py` |
| 垂类 Demo | `examples/demos/` |
| 严格黄金集 / 公开 RAG / capability | `examples/eval/` |
| 成熟度与范围话术 | [`PRODUCTION_MATURITY.md`](PRODUCTION_MATURITY.md) |
| LangGraph 对照 | `experiments/langgraph/` |

## 文档怎么读

1. 本页（结构）
2. [`CORE_ARCHITECTURE.md`](CORE_ARCHITECTURE.md)（控制流）
3. [`AGENT_WORKFLOW.md`](AGENT_WORKFLOW.md)（主路径用法）
4. [`EVAL_INDEX.md`](EVAL_INDEX.md)（评测索引；报告正文在 `reports/`）
5. [`EXPERIMENTAL.md`](EXPERIMENTAL.md)（可选能力）
