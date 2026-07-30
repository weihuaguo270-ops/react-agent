# `react_agent` 包

Python import 路径不变。本页为模块职责分区；仓库总览见 [`docs/STRUCTURE.md`](../../docs/STRUCTURE.md)。

## Core

| 模块 | 职责 |
|------|------|
| `react_loop.py` | ReAct 循环 |
| `workflow/` | 声明式 Workflow 引擎 + builtins |
| `apps/docs_troubleshoot/` | 证据化文档排障（语料 / eval / synthesize / diagnosis） |
| `server/` | HTTP：`/health` `/v1/chat` `/v1/workflows` |
| `tools/` | 工具注册表（含 `list/run_workflow`） |
| `safety/` | 权限闸门 + HITL |
| `harness/` | 轨迹录制 / 回放 / Schema / 沙箱超时 / **StepWatcher 实时失败记录**（需 `trace-debugger`）· **Task Episode**（`task_episode_id` / `acceptance_criteria`） |
| `resilience.py` | ToolGuard（超时/重试） |
| `llm.py` · `prompts.py` · `context.py` · `memory.py` · `cot.py` | LLM 与上下文 |

## Eval

| 模块 | 职责 |
|------|------|
| `eval/` | capability / execution / public agent & RAG 基准 |

入口脚本：`examples/eval/`。

## Experimental

默认不注册进工具表。清单见 [`docs/EXPERIMENTAL.md`](../../docs/EXPERIMENTAL.md)：

- `rag.py` · `mcp_client.py` · `mcp_config.py`
- `orchestrator.py` · `planner.py` · `tot.py`
- `dashboard/`

LangGraph 对照：`experiments/langgraph/`（仓根，非本包）。

## 运行产物（已 gitignore）

`trajectories/` · `.tdebug/` · `memory.json` · `rag_index.json` · `**/_index_cache.json`

### StepWatcher（trace-debugger 集成）

安装 sibling 仓库后，Harness 会在每步工具返回后实时检测失败并写入 JSONL：

```bash
pip install -e ../trace-debugger
# 默认启用；关闭：REACT_AGENT_STEP_WATCHER=0
# 失败日志：src/react_agent/.tdebug/failures.jsonl
```

轨迹 JSON 的 step 上会附带失败标记，例如：

- `failure_tags` / `failure_summary` / `failure_label`
- `failure_detail` / `failure_context` / `failure`（结构化块）

轨迹根级可选字段：`task_episode_id`（eval case id）· `acceptance_criteria`（验收条件）。见 [`docs/HARNESS_HEALTH.md`](../../docs/HARNESS_HEALTH.md)。

失败日志默认目录 `src/react_agent/.tdebug/`（`failures.jsonl`、`failures.log`、`sessions/*.md`）。

聚合统计（需安装 trace-debugger CLI）：

```bash
tdebug stats src/react_agent/.tdebug/failures.jsonl
```
