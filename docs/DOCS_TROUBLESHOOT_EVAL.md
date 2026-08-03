# 证据化文档排障 — 评测

主场景 **docs_troubleshoot** 的**当前能力**：基于内部文档 / Runbook 的问答后端——能引用就引用，没依据就拒答（**不是**完整 API 根因诊断 Agent）。边界与路线图见 [`EVIDENCE_DOCS_TROUBLESHOOT.md`](EVIDENCE_DOCS_TROUBLESHOOT.md)。

本页是 eval 命令和门禁说明：黄金集、仿真故障、生产盲测、Git 文档 held-out。

## 测试集

| 项目 | 说明 |
|------|------|
| 数据集 | `src/react_agent/apps/docs_troubleshoot/golden.json` |
| 规模 | **34 条**（g01–g28 + h01–h06） |
| 语料 | `corpus/` **14 篇** md（演示用 API 参考 + runbook） |
| 默认路径 | **Agent 循环**（`agent_runner`：观测选工具 + `verify_citations` + Harness 轨迹） |
| legacy 路径 | Workflow DAG（`REACT_AGENT_DOCS_ENGINE=workflow`） |
| HTTP 对照 | `POST /v1/chat` 离线默认 = Agent 循环 |

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

## 仿真故障集（field evidence）

```bash
python examples/eval/run_fault_eval.py
```

**12 条**（`fault_sim` + `fault_held_out`）：携带 `error_response` / `request_headers` / **`log_excerpt`** / **`trace_context`**。

报告额外输出 `metrics`：

| 指标 | 含义 |
|------|------|
| `root_cause_hit_rate` | 期望根因 hint 是否出现在 diagnosis |
| `evidence_sufficiency_rate` | 现场证据与规则匹配的平均充分度（0–1） |
| `wrong_suggestion_rate` | 是否出现 `forbid_any` 禁词（fix_steps / answer） |

## 生产盲测（外部语料）

```bash
python examples/eval/run_production_eval.py
```

**5 条**（`prod_blind` + `prod_held_out`）：通过 `REACT_AGENT_DOCS_INGEST_DIRS` 注入 `fixtures/docs_troubleshoot/production_corpus/`，问题**不能**仅靠内置 14 篇 corpus 回答。

| 指标 | 含义 |
|------|------|
| `production_source_hit_rate` | 回答引用 `prod_*.md` 的比例 |
| `avg_evidence_sufficiency` | 诊断证据充分度均值 |

CI 已门禁：golden + fault + production + **git docs** 四套离线 eval。

### Trace 后端（MCP）

```bash
# mock（默认，读 fixtures/docs_troubleshoot/traces/）
set REACT_AGENT_TRACE_BACKEND=mock

# MCP stdio 服务器
set REACT_AGENT_TRACE_BACKEND=mcp
set REACT_AGENT_MCP_CONFIG=fixtures/docs_troubleshoot/mcp_servers.trace.json
```

Workflow 传入 `trace_id` 时自动拉取 Trace（`fetch_trace` 工具亦可手动调用）。

### Git 文档 held_out

```bash
python examples/eval/run_git_docs_eval.py
```

通过 `REACT_AGENT_DOCS_GIT_ROOT` + `ls-files docs/`  ingest 本仓库真实文档，**5 条**冻结用例（`git_held_out` 1 条）。

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
| 根因命中率、错误建议率、证据充分率 | **仿真集已实现**（`run_fault_eval.py` metrics）；历史盲测集仍规划 |
| MTTR、正确升级率 | 规划；需脱敏工单回放 |

实现顺序见 [`EVIDENCE_DOCS_TROUBLESHOOT.md`](EVIDENCE_DOCS_TROUBLESHOOT.md) 三闭环主线。
