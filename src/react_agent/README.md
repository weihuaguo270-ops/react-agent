# `react_agent` 包地图

Python **import 路径不变**。本页只说明职责分区。仓库总览见 [`docs/STRUCTURE.md`](../../docs/STRUCTURE.md)。

## Core（默认主路径）

| 模块 | 职责 |
|------|------|
| `react_loop.py` | ReAct 循环 |
| `workflow/` | 声明式 Workflow 引擎 + builtins |
| `apps/docs_troubleshoot/` | 主场景语料 / 工具 / 严格黄金集 |
| `server/` | 薄 HTTP：`/health` `/v1/chat` `/v1/workflows` |
| `tools/` | 工具注册表（含 `list/run_workflow`） |
| `safety/` | 权限闸门 + HITL |
| `harness/` | 轨迹录制 / 回放 / Schema / 沙箱超时 |
| `resilience.py` | ToolGuard（超时/重试） |
| `llm.py` · `prompts.py` · `context.py` · `memory.py` · `cot.py` | LLM 与上下文 |

## Eval

| 模块 | 职责 |
|------|------|
| `eval/` | capability / execution / public agent & RAG 基准 |

入口脚本在 `examples/eval/`。

## Experimental（默认不进工具表）

见 [`docs/EXPERIMENTAL.md`](../../docs/EXPERIMENTAL.md)：

- `rag.py` · `mcp_client.py` · `mcp_config.py`
- `orchestrator.py` · `planner.py` · `tot.py`
- `dashboard/`

对照实现：`experiments/langgraph/`（仓根，非本包）。

## 运行产物（已 gitignore）

`trajectories/` · `memory.json` · `rag_index.json` · `**/_index_cache.json`
