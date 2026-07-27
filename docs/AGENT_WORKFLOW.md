# Agent 工作流

Core 循环 + **主场景 docs_troubleshoot** + 可选实验能力。生产成熟度见 [`PRODUCTION_MATURITY.md`](PRODUCTION_MATURITY.md)。

## 主路径（Core + 主场景）

```
query → react_loop (REACT_AGENT_APP=docs_troubleshoot)
        → 场景 system prompt
        → LLM (thought / tool_calls)
        → permission gate (deny→ask→allow)
        → search_docs / lookup_api / verify_citations
        → citation policy（无依据拒答）
        → CONTEXT.manage(llm_call=…)
        → FINAL ANSWER + Format B 轨迹
```

HTTP：`python -m react_agent.server` → `POST /v1/chat`（默认离线检索路径；`REACT_AGENT_SERVER_LLM=1` 走真循环）。

## 入口一览

| 能力 | 离线 Demo / 评测 | 环境变量 |
|------|------------------|----------|
| 文档排障（主） | `demo_docs_troubleshoot.py` / `run_docs_troubleshoot_eval.py` | `REACT_AGENT_APP=docs_troubleshoot` |
| HTTP 服务 | `python -m react_agent.server` | 同上 + `DISABLE_MCP=1` |
| Context | `examples/demo_context.py` | — |
| RAG 通用 | `examples/demo_rag.py` | `REACT_AGENT_RAG_MODE=keyword` |
| 报销（辅） | `examples/demo_expense_workflow.py` | keyword |
| MCP mock | `examples/demo_mcp_mock.py` | `REACT_AGENT_MCP_MOCK=1` |

## Context / RAG / MCP

- Context：每步 `CONTEXT.manage(..., llm_call=)`
- RAG：主场景自有语料索引；通用 `rag_query` 仍属实验工具开关
- MCP：服务/评测默认关闭；mock 仅协议冒烟
