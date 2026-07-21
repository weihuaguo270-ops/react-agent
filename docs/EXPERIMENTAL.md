# Experimental modules

这些模块可跑、可学，**不是**核心 ReAct 学习运行时的一部分。默认工具表不注册实验工具；需要时：

```bash
set REACT_AGENT_EXPERIMENTAL_TOOLS=1
```

| Module | Entry | Notes |
|--------|-------|-------|
| RAG | `rag.py`，`pip install -e ".[rag]"` | 多数评测 `SKIP_RAG=1`；`react_loop` 懒加载 ingest |
| MCP | `mcp_client.py` / `--mcp` | 评测默认 `DISABLE_MCP=1`；CLI 路径懒导入 |
| Multi-agent | `orchestrator.py` / `planner.py` | 演示编排；`multi_agent_chain` 懒导入 |
| ToT | `tot.py` | 教学推理工具 |
| Dashboard | `dashboard/` | 本地可视化 |
| LangGraph twin | `experiments/langgraph/` | 框架对照路径；**无严格行为等价测试**；见 `demo_checkpoint_hitl.py` |

安装框架对照依赖：`pip install -e ".[langgraph]"`。  
无 Key 演示：`python experiments/langgraph/demo_checkpoint_hitl.py`。  
契约：`pytest tests/test_langgraph_harness_contract.py`（recorder → Format B；demo 需已装 langgraph）。

`import react_agent.react_loop` 不应拉起 MCP / Orchestrator / RAG（见 `tests/test_core_lazy_imports.py`）。

证据与快照（execution / reliability / κ）见 [`EVAL_INDEX.md`](EVAL_INDEX.md) 与 [`P0_EVIDENCE_MAP.md`](P0_EVIDENCE_MAP.md)，不进本页。
