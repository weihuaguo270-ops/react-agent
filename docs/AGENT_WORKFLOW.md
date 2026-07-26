# Agent 工作流

把 Core 循环接到 Context / RAG / MCP / 业务落点。下列能力可离线演示与回归。

## 主路径（Core）

```
query → react_loop
        → LLM (thought / tool_calls)
        → permission gate (deny→ask→allow)
        → ToolGuard / sandbox
        → observation → CONTEXT.manage(llm_call=…)
        → FINAL ANSWER + Format B 轨迹
```

## 薄弱项补强入口

| 能力 | 离线 Demo | 测试 | 环境变量 |
|------|-----------|------|----------|
| Context | `examples/demo_context.py` | `tests/test_context_manage.py` | 策略见 `context.py` |
| RAG | `examples/demo_rag.py` | `tests/test_rag_keyword.py` | `REACT_AGENT_RAG_MODE=keyword` |
| 业务多步 | `examples/demo_expense_workflow.py` | fixture `fixtures/business/` | 同上 keyword |
| MCP | `examples/demo_mcp_mock.py` | `tests/test_mcp_mock.py` | `REACT_AGENT_MCP_MOCK=1` |

语料：`fixtures/rag_corpus/`（API 入门 + 报销政策示例）。

## Context

- 每步结束：`CONTEXT.manage(messages, llm_call=_context_llm_wrapper)`
- `summarize` / `auto` **必须**带 `llm_call`；未接线时会回退 truncate（旧行为）
- 策略：truncate / drop / summarize / auto

## RAG

- 有 `[rag]`：语义检索；失败或 `REACT_AGENT_RAG_MODE=keyword` → 关键词
- 无向量依赖也可 ingest + query（面试/CI 友好）
- 工具：`rag_query`；库空时返回提示而非硬失败

## MCP

- 真服务器：`--mcp` / `mcp_servers.json` / 便携默认 `uvx mcp-server-time`
- Mock：`REACT_AGENT_MCP_MOCK=1` → `MockMCPClient`（发现工具 + 合并 Schema + call_tool）
- 评测：`REACT_AGENT_DISABLE_MCP=1`

## 业务落点（报销示例）

1. 政策文档入 RAG  
2. 结构化字段（类别/金额/发票）  
3. 规则裁决（可换成 tool）  
4. 结论可写入轨迹，供 eval / tdebug  

诚实边界：示例政策与规则是教学 fixture，不是生产审批系统。
