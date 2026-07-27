# 实验模块

以下模块可运行、可测试，**默认不注册进 Core 工具表**，与主场景 Workflow 路径隔离。启用方式：

```bash
set REACT_AGENT_EXPERIMENTAL_TOOLS=1
```

| Module | Entry | Notes |
|--------|-------|-------|
| RAG | `rag.py`；离线 `REACT_AGENT_RAG_MODE=keyword` | 可选 `pip install -e ".[rag]"` 语义检索；`examples/demos/demo_rag.py` |
| MCP | `mcp_client.py` / `--mcp`；`REACT_AGENT_MCP_MOCK=1` | 评测 `DISABLE_MCP=1`；mock 见 `examples/demos/demo_mcp_mock.py` |
| Multi-agent | `orchestrator.py` / `planner.py` | 编排演示；`multi_agent_chain` 懒导入 |
| ToT | `tot.py` | 教学推理工具 |
| Dashboard | `dashboard/` | 本地可视化 |
| LangGraph twin | `experiments/langgraph/` | 图编排对照；无严格行为等价测试；见 `demo_checkpoint_hitl.py` |

工作流总览：[`AGENT_WORKFLOW.md`](AGENT_WORKFLOW.md)。

LangGraph 依赖：`pip install -e ".[langgraph]"`。  
无 Key 演示：`python experiments/langgraph/demo_checkpoint_hitl.py`。  
契约测试：`pytest tests/test_langgraph_harness_contract.py`（recorder → Format B；demo 需已装 langgraph）。

`import react_agent.react_loop` 不应拉起 MCP / Orchestrator / RAG（见 `tests/test_core_lazy_imports.py`）。

评测快照与 κ 口径见 [`EVAL_INDEX.md`](EVAL_INDEX.md)、[`P0_EVIDENCE_MAP.md`](P0_EVIDENCE_MAP.md)。
