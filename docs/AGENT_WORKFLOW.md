# Agent 工作流

主场景 **docs_troubleshoot**：当前为 [**证据化文档排障**](EVIDENCE_DOCS_TROUBLESHOOT.md)（可引用、可拒答），目标演进为 API 故障诊断 Agent。架构见 [`CORE_ARCHITECTURE.md`](CORE_ARCHITECTURE.md)。

## 默认路径：Workflow（确定性）

黄金集评测走此路径。实现为 **检索 → 片段拼接 → 引用 / 拒答 policy**，非根因推理。

```
query → run_workflow("docs_troubleshoot")
        → search_docs → lookup_api → draft → policy → final
        → 可审计 step 记录 / to_trajectory()
```

```bash
python examples/demos/demo_workflow.py
python -m react_agent.workflow run docs_troubleshoot --query "401 返回什么？"
python examples/eval/run_docs_troubleshoot_eval.py
```

产品边界与三闭环路线图：[`EVIDENCE_DOCS_TROUBLESHOOT.md`](EVIDENCE_DOCS_TROUBLESHOOT.md) · 评测：[`DOCS_TROUBLESHOOT_EVAL.md`](DOCS_TROUBLESHOOT_EVAL.md)。

## 探索路径：react_loop（自由 ReAct）

用于工具组合与 LLM 探索；**不是**当前对外主承诺。下一阶段可承载「验证动作」执行，仍须过权限闸门。

```
query → react_loop (REACT_AGENT_APP=docs_troubleshoot)
        → LLM → permission gate → tools
        → FINAL ANSWER + Format B 轨迹
```

HTTP：`POST /v1/chat`（默认离线；`REACT_AGENT_SERVER_LLM=1` 走真循环）。

## 入口一览

| 能力 | Demo / 评测 | 环境变量 |
|------|-------------|----------|
| 文档问答 Workflow | `demo_workflow.py` / `run_docs_troubleshoot_eval.py` | `REACT_AGENT_APP=docs_troubleshoot` |
| 工具级演示 | `demo_docs_troubleshoot.py` | 同上 |
| HTTP 服务 | `python -m react_agent.server` | 同上 |
| Context / RAG / MCP / 报销 | `examples/demos/*` | 实验能力，见 [`EXPERIMENTAL.md`](EXPERIMENTAL.md) |

## Context / RAG / MCP

- 主场景语料：`apps/docs_troubleshoot/corpus/`（当前 14 篇演示 md）
- 通用 `rag_query` / MCP：实验开关，非下一阶段主线
