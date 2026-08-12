# Agent 工作流

主场景 **docs_troubleshoot**：当前为 [**证据化文档排障**](EVIDENCE_DOCS_TROUBLESHOOT.md)（可引用、可拒答），目标演进为 API 故障诊断 Agent。架构见 [`CORE_ARCHITECTURE.md`](CORE_ARCHITECTURE.md)。

## 默认路径：离线 Agent 循环

`docs_troubleshoot`、HTTP 服务和黄金集评测默认走 `agent_runner`。该路径根据当前观测选择
`search_docs`、`lookup_api`、`verify_citations` 等工具，并记录 Format B 轨迹；它仍以规则和
检索证据为主，不应表述为自动根因推理。

```
query → run_docs() → agent_runner
        → observe → select tool → verify citations → policy → final
        → Harness Format B trajectory
```

```bash
python examples/eval/run_docs_troubleshoot_eval.py
python -m react_agent.server --port 8765
```

产品边界与三闭环路线图：[`EVIDENCE_DOCS_TROUBLESHOOT.md`](EVIDENCE_DOCS_TROUBLESHOOT.md) · 评测：[`DOCS_TROUBLESHOOT_EVAL.md`](DOCS_TROUBLESHOOT_EVAL.md)。

## Live 路径：react_loop（LLM ReAct）

用于真实 LLM 的工具组合与多步执行。HTTP 设置 `REACT_AGENT_SERVER_LLM=1` 后走该路径；
工具调用仍须经过权限闸门和选定的 Sandbox 后端。

```
query → react_loop (REACT_AGENT_APP=docs_troubleshoot)
        → LLM → permission gate → tools
        → FINAL ANSWER + Format B 轨迹
```

HTTP：`POST /v1/chat`（默认离线；`REACT_AGENT_SERVER_LLM=1` 走真循环）。

## 兼容路径：Workflow（legacy DAG）

确定性 Workflow 保留用于对照、显式演示和历史结果复现，不再是默认路径。通过
`REACT_AGENT_DOCS_ENGINE=workflow` 或 workflow CLI 显式启用。

```bash
set REACT_AGENT_DOCS_ENGINE=workflow
python examples/demos/demo_workflow.py
python -m react_agent.workflow run docs_troubleshoot --query "401 返回什么？"
```

## 入口一览

| 能力 | Demo / 评测 | 环境变量 |
|------|-------------|----------|
| 离线文档 Agent | `run_docs_troubleshoot_eval.py` / HTTP | `REACT_AGENT_APP=docs_troubleshoot` |
| Legacy Workflow | `demo_workflow.py` / workflow CLI | `REACT_AGENT_DOCS_ENGINE=workflow` |
| 工具级演示 | `demo_docs_troubleshoot.py` | 同上 |
| HTTP 服务 | `python -m react_agent.server` | 同上 |
| Context / RAG / MCP / 报销 | `examples/demos/*` | 实验能力，见 [`EXPERIMENTAL.md`](EXPERIMENTAL.md) |

## Context / RAG / MCP

- 主场景语料：`apps/docs_troubleshoot/corpus/`（当前 14 篇演示 md）
- 通用 `rag_query` / MCP：实验开关，非下一阶段主线
