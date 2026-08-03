# 应用方向（主流 Agent 三条主线）

本仓 **Agent 运行时**（`react_loop` + ToolGuard + Harness + 权限闸门）服务于 GitHub / 行业里的 **三条主流应用方向**，而不是单一窄垂直。

| 主线 | 典型任务 | 本仓入口 | 评测 / 证据 |
|------|----------|----------|-------------|
| **① 写代码 / 执行** | 工具调用、多步推理、Issue 式任务 | `react_loop` · `run_execution_suite.py` · HTTP `app=default` | execution 36 条 agent · HTTP smoke 3 条 |
| **② 客服 / 自动化** | 政策问答、工作流、可部署 Chat API | `demo_expense_workflow.py` · `server` · `apps/docs_troubleshoot` | docs 黄金集 34 · fault 12 · HTTP smoke |
| **③ 通用 RAG / 研究** | 检索增强、公开 QA、Deep Research 形 | `demo_rag.py` · `run_public_rag_benchmark.py` | GSM8K+Hotpot 20 · public RAG 分层 |

**证据化文档排障**（`docs_troubleshoot`）是 **② 客服/知识自动化** 下的 **一个垂直 demo**（引用 + 拒答 + 现场证据），不是全仓唯一产品名。

---

## ① 写代码 / 执行 Agent

**主流对标：** OpenHands、SWE-agent、IDE/CLI Agent。

**本仓有什么：**

- `react_loop` — ReAct + function calling + ToolGuard + duplicate 拦截 + Harness 轨迹
- 工具：`calculator`、`web_search`、`execute_python`（CONFIRM）、MCP（可选）
- Execution 任务集：`src/react_agent/eval/execution_dataset.json`（offline_tools + **agent 36 条**）
- Capability 集：多工具 / 角色 / 推理：`capability_dataset.json`

**怎么跑：**

```bash
python -m react_agent "用 calculator 算 17*19"
python examples/eval/run_execution_suite.py              # offline_tools
python examples/eval/run_execution_suite.py --modes agent   # 需 API Key
# HTTP（Pillar ① smoke，需 REACT_AGENT_SERVER_OFFLINE_REACT=1 或 SERVER_LLM=1）
python examples/eval/run_execution_http_smoke.py --url http://127.0.0.1:8765
```

**差异化（运行时，非应用）：** 权限闸门、StepWatcher、failure flywheel、Format B 轨迹 — 见 [`CORE_ARCHITECTURE.md`](CORE_ARCHITECTURE.md)。

**下一步：** 扩 execution HTTP smoke 覆盖面；sandbox 读改测任务模板。

---

## ② 客服 / 工作流自动化

**主流对标：** Dify 工作流、Zendesk/Fin 类知识客服、内部 Copilot。

**本仓有什么：**

- **可部署 HTTP 服务：** `python -m react_agent.server` · Docker · 产品 UI（`/`）
- **业务工作流 demo：** `examples/demos/demo_expense_workflow.py`（政策检索 + 裁决）
- **垂直知识客服 demo：** `apps/docs_troubleshoot` — 引用 / 拒答 / verify 工具步 / diagnosis
- **离线 Agent 循环：** `agent_runner`（CI 不耗 Key）

**怎么跑：**

```bash
python examples/demos/demo_expense_workflow.py
docker compose up --build    # http://127.0.0.1:8765/
python examples/eval/run_docs_troubleshoot_eval.py
```

**docs_troubleshoot 的位置：** 演示 **「有依据才答、没依据拒答」的客服/Runbook 后端**，不是完整 AIOps 平台。

**v0.5 已完成：** `/v1/chat` 多 app（`docs_troubleshoot` | `expense` | `default`）；`GET /v1/info` 列出 applications。

**下一步：** 结构化 JSON 日志 + Bearer 鉴权；expense Live 路径；neutral 多 app UI。

---

## ③ 通用 RAG / 研究 Agent

**主流对标：** LlamaIndex document agent、Deep Research、HotpotQA 类 multi-hop。

**本仓有什么：**

- RAG：`rag.py` · `demo_rag.py` · `REACT_AGENT_RAG_MODE=keyword|semantic`
- 公开 Agent 子集：GSM8K×10 + HotpotQA×10 — `run_public_benchmark.py`
- 公开 RAG 分层：HotpotQA-RAG smoke/hard/held_out — `run_public_rag_benchmark.py`
- 研究形能力：ToT / Planner / Orchestrator（实验轨，见 [`EXPERIMENTAL.md`](EXPERIMENTAL.md)）

**怎么跑：**

```bash
set REACT_AGENT_EXPERIMENTAL_TOOLS=1
python examples/demos/demo_rag.py
python examples/eval/run_public_benchmark.py
python examples/eval/run_public_rag_benchmark.py
```

**下一步：** public RAG/agent 子集与 docs 黄金集 **并列** CI 门禁（execution HTTP smoke 已并列）。

---

## 默认入口怎么选

| 你想展示… | 默认命令 |
|-----------|----------|
| Agent 能调工具、有轨迹 | `python -m react_agent "…"` 或 execution suite |
| 能部署的 Chat / 知识客服 | `docker compose up` + `/v1/chat` |
| 检索 + 公开 QA | `run_public_benchmark.py` / `demo_rag.py` |
| 垂直 Runbook（窄 demo） | `REACT_AGENT_APP=docs_troubleshoot` |

**仓库默认叙事：** 运行时 + 三条主流应用；**不再**把全仓等同于「证据化文档排障」单一产品。

---

## 与跨仓生态

| 仓 | 在三条主线中的作用 |
|----|-------------------|
| **react-agent** | 执行运行时 + 三套 eval 证据 |
| **trace-debugger** | 轨迹 scan / Harness Health（①②③ 共用） |
| **llm-eval-engine** | Process Reward / 人机校准（①③ 为主） |

---

## 文档索引

- 架构：[`CORE_ARCHITECTURE.md`](CORE_ARCHITECTURE.md)
- 评测：[`EVAL_INDEX.md`](EVAL_INDEX.md)
- 垂直 demo：[`EVIDENCE_DOCS_TROUBLESHOOT.md`](EVIDENCE_DOCS_TROUBLESHOOT.md)
- 实验：[`EXPERIMENTAL.md`](EXPERIMENTAL.md)
