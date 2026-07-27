# Agent 工作流

**自建 Core** = ReAct + **声明式 Workflow** + 主场景 docs_troubleshoot。架构见 [`CORE_ARCHITECTURE.md`](CORE_ARCHITECTURE.md)。

## 推荐主路径：Workflow（确定性）

```
query → run_workflow("docs_troubleshoot")
        → search_docs → lookup_api → draft → policy → final
        → 可审计 step 记录 / to_trajectory()
```

```bash
python examples/demos/demo_workflow.py
python -m react_agent.workflow run docs_troubleshoot --query "401 返回什么？"
```

HTTP：`GET /v1/workflows`，`POST /v1/workflows/run`。

严格黄金集（无 must_* 泄漏、只评最终 answer）：

```bash
python examples/eval/run_docs_troubleshoot_eval.py
```

## 探索路径：react_loop（自由 ReAct）

```
query → react_loop (REACT_AGENT_APP=docs_troubleshoot)
        → LLM (thought / tool_calls；可调用 run_workflow)
        → permission gate → tools
        → FINAL ANSWER + Format B 轨迹
```

HTTP：`POST /v1/chat`（默认离线；`REACT_AGENT_SERVER_LLM=1` 走真循环）。

## 入口一览

| 能力 | 离线 Demo / 评测 | 环境变量 |
|------|------------------|----------|
| **Workflow 排障（推荐）** | `demo_workflow.py` / `python -m react_agent.workflow` | `REACT_AGENT_APP=docs_troubleshoot` |
| 文档排障（工具级） | `demo_docs_troubleshoot.py` / `run_docs_troubleshoot_eval.py` | 同上 |
| HTTP 服务 | `python -m react_agent.server` | 同上 |
| Context | `examples/demos/demo_context.py` | — |
| RAG 通用 | `examples/demos/demo_rag.py` | `REACT_AGENT_RAG_MODE=keyword` |
| 报销（辅） | `examples/demos/demo_expense_workflow.py` | keyword |
| MCP mock | `examples/demos/demo_mcp_mock.py` | `REACT_AGENT_MCP_MOCK=1` |

## Context / RAG / MCP

- Context：每步 `CONTEXT.manage(..., llm_call=)`
- RAG：主场景自有语料索引；通用 `rag_query` 仍属实验工具开关
- MCP：服务/评测默认关闭；mock 仅协议冒烟
