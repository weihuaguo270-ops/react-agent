# 证据化文档排障 — 评测

主场景 **docs_troubleshoot** 的**当前能力**是：基于内部文档 / Runbook、答案可引用、无依据可拒答的问答后端（**不是**完整 API 根因诊断 Agent）。产品定位与路线图见 [`EVIDENCE_DOCS_TROUBLESHOOT.md`](EVIDENCE_DOCS_TROUBLESHOOT.md)。

本页描述**现有**黄金集回归；下一阶段评测指标（根因命中率等）在路线图中有定义，尚未实现。

## 测试集

| 项目 | 说明 |
|------|------|
| 数据集 | `src/react_agent/apps/docs_troubleshoot/golden.json` |
| 规模 | **34 条**（g01–g28 + h01–h06） |
| 语料 | `corpus/` **14 篇** md（演示用 API 参考 + runbook） |
| 默认路径 | Workflow `docs_troubleshoot`（离线、无 LLM Key） |
| 对照路径 | `chat_offline`（与 HTTP `POST /v1/chat` 默认离线路径一致） |

**局限**：黄金集衡量的是「问法 → 语料片段 → 引用 / 关键词 / 拒答」，不能代表真实企业文档规模、现场日志或 OpenAPI 自动诊断。

## 难度分层（`tag`）

| tag | 数量 | 考察点 |
|-----|------|--------|
| **core** | 13 | 单文档标准问答 |
| **hard** | 10 | 多条件、禁词、跨字段 |
| **refuse** | 5 | 域外 / 危险请求须拒答 |
| **held_out** | 6 | 设计后冻结；分栏报告，不对其调参 |

每条另有 `expect`：`answer`（须引用）或 `refuse`（须拒答）。

## 严格性（防泄漏）

- 检索 / 运行**只用原始 question**，不注入 `must_*`
- **只评最终 answer**，检索 blob 中的关键词不算过
- 不向 draft 塞期望关键词；拒答由统一 `should_refuse_query` 判定

## 运行与展示

```bash
python examples/eval/run_docs_troubleshoot_eval.py
python examples/eval/run_docs_troubleshoot_eval.py --path chat_offline
python examples/eval/run_docs_troubleshoot_eval.py --publish
python examples/eval/run_docs_troubleshoot_eval.py --gate non_held_out
```

输出 JSON：`passed` / `total` / `by_tag` / `rows[]` / `leakage_guards`。

CI：`tests/test_docs_troubleshoot.py` — Workflow 与 chat_offline 全量 PASS。

## 与周边评测

| 评测 | 关系 |
|------|------|
| golden 34 | **主场景当前回归门禁**（文档问答 + 引用） |
| `public_rag_benchmark` | 通用 RAG 外部可比，非排障专用 |
| `capability` / `execution` | 通用 Agent 能力轨 |

## 评测演进（规划）

| 指标 | 状态 |
|------|------|
| pass_rate、引用、拒答 | **已实现**（本页） |
| 根因命中率、错误建议率、证据充分率 | 规划；需历史故障盲测集 |
| MTTR、正确升级率 | 规划；需脱敏工单回放 |

实现顺序见 [`EVIDENCE_DOCS_TROUBLESHOOT.md`](EVIDENCE_DOCS_TROUBLESHOOT.md) 三闭环主线。
