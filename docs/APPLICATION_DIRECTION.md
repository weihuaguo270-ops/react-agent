# 应用方向（企业业务线 + 共享能力）

本仓面向企业任务执行与 Agent 评测，重点是可量化的业务结果和可复现的过程证据，而不是证明 Agent 能调用工具。
当前将项目划分为两条企业业务线、一组跨域 benchmark 和一层共享能力。指标定义和证据边界见
[`ENTERPRISE_AGENT_SCOPE.md`](ENTERPRISE_AGENT_SCOPE.md)。

| 层级 | 典型任务 | 本仓入口 | 评测 / 证据 |
|------|----------|----------|-------------|
| **业务线 ① 软件工程交付** | Issue、读改测、审批、候选提交 | `apps/github_delivery.py` · `GITHUB_DELIVERY_WORKFLOW.md` | 验收测试、任务成功、人工介入、外部写入、P95 |
| **业务线 ② 技术支持/工单辅助** | 现场证据、根因候选、验证、修复建议 | `apps/docs_troubleshoot` · `server` | docs 34、fault 12、production 5；证据化解决和错误建议 |
| **跨域 benchmark 场景** | 安全研判、报销审核、公开仓库质量 | `apps/security_triage` · `apps/expense` · `apps/github_delivery` | 用于风险边界、业务终态和评测迁移验证，不单独扩张为产品线 |
| **共享能力层** | RAG、多跳检索、轨迹、权限、Episode、过程评测 | `rag.py` · Harness · Sandbox · eval | 统一输出 `evaluation-episode/v1`，交给 `llm-eval-engine` 和 `trace-debugger` |

报销、安全研判和通用执行保留为业务状态验证与能力回归示例；它们是跨域 benchmark，不是新增企业主业务线。

---

## ① 软件工程交付 Agent

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

**差异化（业务交付）：** Issue 到候选提交的受控闭环；权限闸门、StepWatcher、failure flywheel、Format B 轨迹是共享运行时能力 — 见 [`CORE_ARCHITECTURE.md`](CORE_ARCHITECTURE.md)。

**已补充：** [`GITHUB_DELIVERY_WORKFLOW.md`](GITHUB_DELIVERY_WORKFLOW.md) 提供真实 Git 隔离克隆、读改测、影子运行、计划指纹审批、幂等审计、候选提交和可选 Draft PR。独立
[`agent-delivery-sandbox`](https://github.com/weihuaguo270-ops/agent-delivery-sandbox)
已完成 24 条合成 Issue 的 Shadow 运行、4 条受控 Draft PR、3 条接受、1 条拒绝及 1 次合并后回滚。
这是 `external_real_sandbox` 证据，不代表生产流量或真实用户任务。

---

## ② 技术支持 / 工单辅助 Agent

**主流对标：** 企业 Runbook Copilot、知识库辅助排障、工单分诊与升级系统。

**本仓有什么：**

- **可部署 HTTP 服务：** `python -m react_agent.server` · Docker · 产品 UI（`/`）
- **垂直技术支持 demo：** `apps/docs_troubleshoot` — 现场证据、引用 / 拒答 / verify 工具步 / diagnosis
- **业务状态验证示例：** `apps/expense` — 用于回归业务状态验证，不代表主业务线
- **安全研判 benchmark / 垂直 MVP：** `apps/security_triage` — CVE/KEV/ATT&CK/IOC 公开情报、资产/SBOM 关联、版本化案件、引用报告与人工复核；严格只读，并原生输出 `evaluation-episode/v1` 供跨仓评测
- **离线 Agent 循环：** `agent_runner`（CI 不耗 Key）

**怎么跑：**

```bash
python examples/demos/demo_expense_workflow.py
docker compose up --build    # http://127.0.0.1:8765/
python examples/eval/run_docs_troubleshoot_eval.py
```

**docs_troubleshoot 的位置：** 演示 **「有依据才答、没依据拒答」的技术支持/Runbook 后端**，不是完整工单 SaaS 或 AIOps 平台。

**多应用入口：** `/v1/chat` 支持 `docs_troubleshoot` | `expense` | `security_triage` | `default`；`GET /v1/info` 列出 applications。安全研判边界见 [`SECURITY_TRIAGE_AGENT.md`](SECURITY_TRIAGE_AGENT.md)。

**下一步：** Bearer 鉴权；expense Live 路径；neutral 多 app UI。工程交付流程已经输出结构化审计和告警，但 HTTP 服务全链路 JSON 日志仍需单独补齐。

---

## 共享能力：RAG / 研究回归

**用途：** 验证共享检索、multi-hop 和工具编排能力，不作为第三条业务产品线。

**本仓有什么：**

- RAG：`rag.py` · `demo_rag.py` · `REACT_AGENT_RAG_MODE=keyword|semantic`；本地 JSON 默认，
  可用 `REACT_AGENT_RAG_BACKEND=milvus` 接入共享向量库
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

**仓库默认叙事：** 两条企业业务线 + 跨域 benchmark + 共享运行时/评测能力；**不再**把全仓等同于「证据化文档排障」或「安全研判」单一产品。

---

## 与跨仓生态

| 仓 | 在业务线与共享能力中的作用 |
|----|-------------------|
| **react-agent** | 执行运行时 + 业务场景适配 + `EvaluationEpisode` 产出 |
| **trace-debugger** | 轨迹 scan / Harness Health（两条业务线共用） |
| **llm-eval-engine** | Process Reward / 人机校准（共享过程评测能力） |

---

## 文档索引

- 架构：[`CORE_ARCHITECTURE.md`](CORE_ARCHITECTURE.md)
- 评测：[`EVAL_INDEX.md`](EVAL_INDEX.md)
- 垂直 demo：[`EVIDENCE_DOCS_TROUBLESHOOT.md`](EVIDENCE_DOCS_TROUBLESHOOT.md)
- 实验：[`EXPERIMENTAL.md`](EXPERIMENTAL.md)
