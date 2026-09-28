# 实验模块

以下模块可运行、可测试，**默认不注册进 Core 工具表**，与主场景 Workflow 路径隔离。启用方式：

```bash
set REACT_AGENT_EXPERIMENTAL_TOOLS=1
```

| Module | Entry | Notes |
|--------|-------|-------|
| RAG | `rag.py`；离线 `REACT_AGENT_RAG_MODE=keyword` | 可选 `pip install -e ".[rag]"` 语义检索；`examples/demos/demo_rag.py` |
| MCP | `mcp_client.py` / `--mcp`；`REACT_AGENT_MCP_MOCK=1` | 评测 `DISABLE_MCP=1`；mock 见 `examples/demos/demo_mcp_mock.py` |
| Multi-agent | `orchestrator.py` / `planner.py` / `tool_scope.py` / `write_sets.py` | 见下方专节；`multi_agent_chain` 懒导入，不随 `import react_loop` 拉起 |
| ToT | `tot.py` | 教学推理工具 |
| Dashboard | `dashboard/` | 本地可视化 |
| LangGraph twin | `experiments/langgraph/` | 图编排对照；无严格行为等价测试；见 `demo_checkpoint_hitl.py` |

工作流总览：[`AGENT_WORKFLOW.md`](AGENT_WORKFLOW.md)。

### Multi-agent（Orchestrator / Worker）现状

`orchestrator.py` + `planner.py` 已不只是"编排演示"：Worker 工具面按 `ToolScope`
**声明式收窄**（未知工具名告警，`REACT_AGENT_SCOPE_STRICT=1` 抛错）、同层**写冲突
检测默认开启**、委派深度与并发有显式上限、支持摘要式 `context: fork`。完整能力
边界与配置项见 [`CORE_ARCHITECTURE.md`](CORE_ARCHITECTURE.md#orchestrator--worker-的能力边界含无工作区隔离的声明)。

⚠️ **并行 Worker 无工作区隔离**：共享同一进程与工作目录，并行改同一文件仍会
互相覆盖；当前安全依赖「写集声明 + 冲突分层」这套调度约定，不是隔离机制。

`tool_scope.py` / `write_sets.py` 放在包顶层（而非 `tools/` 内）是刻意的：它们是
Core 路径模块，导入时不得触发 `tools` 包的 app/workflow/experimental 装配。

LangGraph 依赖：`pip install -e ".[langgraph]"`。  
无 Key 演示：`python experiments/langgraph/demo_checkpoint_hitl.py`。  
契约测试：`pytest tests/test_langgraph_harness_contract.py`（recorder → Format B；demo 需已装 langgraph）。

`import react_agent.react_loop` 不应拉起 MCP / Orchestrator / RAG（见 `tests/test_core_lazy_imports.py`）。
注：RAG 曾因 `apps/docs_troubleshoot/tools.py` 的模块级 `index` 导入而被连带装配，
现已改为按需导入（`import react_loop` 实测 2.46s → 1.32s）。

评测快照与 κ 口径见 [`EVAL_INDEX.md`](EVAL_INDEX.md)、[`P0_EVIDENCE_MAP.md`](P0_EVIDENCE_MAP.md)。
