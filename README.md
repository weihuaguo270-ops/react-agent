# ReAct Agent

[![CI](https://github.com/weihuaguo270-ops/react-agent/actions/workflows/test.yml/badge.svg)](https://github.com/weihuaguo270-ops/react-agent/actions/workflows/test.yml) [![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org) [![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE) [![scope](https://img.shields.io/badge/应用-编码·客服/RAG·研究-lightgrey)](docs/APPLICATION_DIRECTION.md)

个人维护的 **Agent 运行时**（`react_loop` + ToolGuard + Harness + 权限闸门），面向 GitHub 主流的三类应用：**写代码/执行**、**客服与工作流自动化**、**通用 RAG/研究**。详见 [`docs/APPLICATION_DIRECTION.md`](docs/APPLICATION_DIRECTION.md)。

结构：[`docs/STRUCTURE.md`](docs/STRUCTURE.md) · 架构：[`docs/CORE_ARCHITECTURE.md`](docs/CORE_ARCHITECTURE.md) · 评测：[`docs/EVAL_INDEX.md`](docs/EVAL_INDEX.md) · 成熟度：[`docs/PRODUCTION_MATURITY.md`](docs/PRODUCTION_MATURITY.md)。

## 业务目标

我把这个项目定位为 **Agent 业务的执行底座**：业务方提供任务、工具和验收标准，运行时负责受控调用工具、记录完整轨迹，并把结果交给评测和失败治理系统。它优先服务三类可复用场景：编码/执行、客服/工作流自动化、RAG/研究。

| 负责人关注的问题 | 项目交付 |
|------------------|----------|
| Agent 是否在权限边界内完成任务 | 权限闸门、ToolGuard、可切换的工具隔离 |
| 结果能否被业务和质量团队复核 | 引用/拒答策略、Format B 轨迹、Task Episode 验收标准 |
| 失败是否能进入回归闭环 | Harness、StepWatcher、离线/HTTP eval 和跨仓接口 |
| 能否作为应用原型交付验证 | 多 app HTTP、Web UI、Docker 与可复现演示 |

**当前阶段：** 已形成可部署、可评测的工程原型；尚未证明多租户隔离、真实业务 SLA、长期线上流量稳定性或企业权限体系集成。

## 三大应用方向

| 方向 | 做什么 | 快速入口 |
|------|--------|----------|
| **① 写代码 / 执行** | ReAct 调工具、多步任务、轨迹可回放 | `python -m react_agent "用 calculator 算 17*19"` · [`run_execution_suite.py`](examples/eval/run_execution_suite.py) · HTTP: [`run_execution_http_smoke.py`](examples/eval/run_execution_http_smoke.py) |
| **② 客服 / 自动化** | 可部署 Chat API、政策/Runbook 问答、工作流 demo | `docker compose up` · [`demo_expense_workflow.py`](examples/demos/demo_expense_workflow.py) |
| **③ RAG / 研究** | 检索增强、公开 QA 子集、multi-hop | [`demo_rag.py`](examples/demos/demo_rag.py) · [`run_public_benchmark.py`](examples/eval/run_public_benchmark.py) |

**Since v0.5.0：** `POST /v1/chat` 支持 `app=docs_troubleshoot|expense|default`；`GET /v1/info` 列出 applications。默认离线 app 由 `REACT_AGENT_DEFAULT_APP` 控制（兼容旧 `REACT_AGENT_APP`）。

**垂直 demo（② 的子场景）：** [证据化文档排障](docs/EVIDENCE_DOCS_TROUBLESHOOT.md) — 引用/拒答/现场证据；`agent_runner` 默认离线循环 · Live 走 `react_loop`。

```bash
# ① 执行 Agent
python examples/eval/run_execution_suite.py --modes agent

# ② 可部署客服 / Runbook 后端
docker compose up --build
python examples/eval/run_docs_troubleshoot_eval.py

# ③ 公开 RAG/QA
python examples/eval/run_public_benchmark.py
python examples/eval/run_public_rag_benchmark.py
```

## 垂直 demo：证据化文档排障

```bash
set REACT_AGENT_APP=docs_troubleshoot
set REACT_AGENT_RAG_MODE=keyword
python examples/demos/demo_workflow.py                   # 确定性 Workflow（legacy DAG）
python -m react_agent.workflow run docs_troubleshoot --query "401 返回什么？"
python examples/eval/run_docs_troubleshoot_eval.py      # 黄金集 34 条（默认 agent 路径）
python examples/eval/run_fault_eval.py                  # 故障模拟 12 条
python examples/eval/run_production_eval.py             # 生产盲测 5 条
python examples/eval/run_git_docs_eval.py               # Git 文档 held-out 5 条
python -m react_agent.server --port 8765           # 浏览器 http://127.0.0.1:8765/ · 产品 UI
docker compose up --build                         # 同上 · 见 docs/DEPLOY.md
```

Workflow v5（legacy DAG）：`现场证据 → search → lookup_api → synthesize → policy → diagnosis`。  
**默认运行时**为 **Agent 循环**（`agent_runner.py`）：根据观测选工具、强制 `verify_citations`、写 Harness 轨迹；Live 模式用 `react_loop` + LLM。详见 [`EVIDENCE_DOCS_TROUBLESHOOT.md`](docs/EVIDENCE_DOCS_TROUBLESHOOT.md) · 评测：[`DOCS_TROUBLESHOOT_EVAL.md`](docs/DOCS_TROUBLESHOOT_EVAL.md) · **Since v0.4.0**。

**产品特色 vs 可视化：** 差异化在 **Agent 运作本身** — 工具选择循环、引用校验工具步、权限闸门、Harness 轨迹与 failure flywheel；eval 是验收手段而非卖点。可视化 **中等**：内置 Web UI（`/`）展示证据链与 agent 步数；CLI + JSON + 轨迹文件仍是回归主路径。

## 范围与定位

| 是 | 不是 |
|----|------|
| **三类主流应用**：编码执行 · 客服/自动化 · RAG/研究（见 APPLICATION_DIRECTION） | 单一「文档排障」产品或 AIOps 平台 |
| Agent 运行时 + 循环治理（ToolGuard、Harness、权限、轨迹飞轮） | 图编排平台 / LangGraph 替代品 |
| 可部署 HTTP + Docker + 多套 eval 证据 | 多租户 SLA / 自动线上根因 |

跨仓：**本仓 Core** = 执行 + capability 规则打分；**llm-eval-engine** = Process Reward / 人机校准；**trace-debugger** = 轨迹启发式复盘 + Harness Health 门禁。共享约定见 [`schemas/harness_trajectory.schema.json`](schemas/harness_trajectory.schema.json)。

证据地图：[`docs/P0_EVIDENCE_MAP.md`](docs/P0_EVIDENCE_MAP.md) · Harness 五维健康度：[`docs/HARNESS_HEALTH.md`](docs/HARNESS_HEALTH.md)。

## 架构概览

```
query
  ├─ react_loop（默认 Live：① 编码/执行 · ③ 研究）
  ├─ agent_runner / server（② 客服/自动化 · docs_troubleshoot demo）
  └─ Workflow DAG（legacy，REACT_AGENT_DOCS_ENGINE=workflow）
        → permission gate → tools / ToolGuard → Format B 轨迹
```

| 维度 | Core（默认） |
|------|----------------|
| **入口** | `agent_runner` / `react_loop()` / `python -m react_agent.server` |
| **依赖** | 标准库 + LLM API（离线 Agent 可不需 Key） |
| **侧重点** | 主流 ReAct 形态 + 循环内治理、Harness、评测验收 |

### 执行流程（Core）

```
query
  ├─ run_docs() → agent_runner（默认）
  │     观测 → search/lookup/parse_* → verify_citations → policy → diagnosis
  ├─ react_loop()（Live）
  │     LLM 选工具 → 同一套 docs 工具与 prompt
  └─ run_workflow("docs_troubleshoot")（legacy DAG）
```

多 Agent / MCP / RAG / LangGraph 为**实验对照**，见 [`docs/EXPERIMENTAL.md`](docs/EXPERIMENTAL.md)。成熟度评判见 [`docs/PRODUCTION_MATURITY.md`](docs/PRODUCTION_MATURITY.md)。

### 模块清单

完整地图见 [`docs/STRUCTURE.md`](docs/STRUCTURE.md)。精简树：

```
src/react_agent/          # Core 默认
├── workflow/ · react_loop.py · apps/docs_troubleshoot/ · server/
├── tools/ · safety/ · harness/ · resilience.py · eval/
examples/
├── demos/                # 演示
└── eval/                 # 回归与公开基准
docs/                     # STRUCTURE · CORE · EVAL_INDEX；报告在 reports/
experiments/langgraph/    # 可选对照（非默认）
```

## 核心功能

### 多 Provider LLM 支持

优先读取项目根目录 `.env` / `llm_config.json`（`.env` 会覆盖系统里残留的旧 API Key），也可用环境变量切换 provider：

```bash
export LLM_PROVIDER=deepseek   # 或 openai / anthropic
```

### 权限与沙箱（两层）

**Permissions（准不准）** 与 **Sandbox（崩不崩）** 是两层，互不替代：

| 层 | 模块 | 职责 |
|----|------|------|
| 权限闸门 | `safety/permissions.py` + `permission_gate.py` | deny → ask → allow；**模型 tool_call ≠ 允许执行** |
| 工具隔离 | `harness/sandbox.py` | 开发用进程后端；生产用失败关闭的容器后端 |

权限评估顺序（Harness 强制）：

1. **DENY** — 参数 DENY 规则或工具表 DENY（默认拦截）
2. **ASK** — CONFIRM（有 HITL 则询问；非交互默认放行，可用 `REACT_AGENT_STRICT_CONFIRM=1` 收紧）
3. **ALLOW** — SAFE / NOTIFY

关闭权限闸门：`REACT_AGENT_PERMISSION_GATE=0`。

工具名表 + 参数规则示例（`safety/permissions.py`）：

| 等级 | 行为 | 适用场景（示例） |
|------|------|------------------|
| SAFE | 自动放行 | web_search、calculator |
| NOTIFY | 记录后继续 | 部分读信息工具 |
| CONFIRM | 询问 / 非交互默许 | write_file、execute_python |
| DENY | 默认拦截 | delete_directory、install_package |

范围与限制：
- 权限层 **不是** OS ACL；未知工具名会进入 Sandbox，但权限表仍应显式登记。
- `process` 后端仅隔离崩溃/超时；不可信代码必须使用 `container` 后端。
- `container + required` 实施非 root、只读根、默认断网和资源限额；运行时不可用时失败关闭。
- 严格容器模式禁止 MCP 宿主直连，需要独立隔离 Broker。

`harness/sandbox.py` 支持 `off` / `auto` / `on` 和 `process` / `container`。
生产配置与威胁模型见 [`docs/SANDBOX_SECURITY.md`](docs/SANDBOX_SECURITY.md)。

### 执行轨迹（Harness）

每步 thought / action / observation 写入 Format B JSON，供回放和跨仓对接（`harness/recorder.py` → `schemas/harness_trajectory.schema.json`）。

**Task Episode**（v0.2.7+）：轨迹可携带 `task_episode_id` 与 `acceptance_criteria`，与 eval case 对齐，供 trace-debugger scan/compare 与 Process Reward 共用验收边界。详见 [`docs/HARNESS_HEALTH.md`](docs/HARNESS_HEALTH.md)。

```python
from react_agent.harness.recorder import start_trajectory, current_trajectory

start_trajectory(
    query="17 * 19",
    task_episode_id="exec_calc_mul",
    acceptance_criteria=["tool calculator returns 323"],
)
result = react_loop("17 * 19")
trajectory = current_trajectory()

# 逐步骤回放
from react_agent.harness.replay import replay_trajectory
replay_trajectory(trajectory)
```

安装 sibling [trace-debugger](https://github.com/weihuaguo270-ops/trace-debugger) 后，Harness 默认启用 **StepWatcher** 实时失败记录；发版前可 `tdebug scan … --compare --findings-out` 做回归门禁。

### RAG / MCP / Context / 业务 Demo

三条主线的 demo 入口见 [`docs/APPLICATION_DIRECTION.md`](docs/APPLICATION_DIRECTION.md)。工作流总览：[`docs/AGENT_WORKFLOW.md`](docs/AGENT_WORKFLOW.md)、[`docs/EXPERIMENTAL.md`](docs/EXPERIMENTAL.md)。

```bash
set REACT_AGENT_EXPERIMENTAL_TOOLS=1
set REACT_AGENT_RAG_MODE=keyword
set REACT_AGENT_MCP_MOCK=1
python examples/demos/demo_context.py
python examples/demos/demo_rag.py
python examples/demos/demo_expense_workflow.py
python examples/demos/demo_mcp_mock.py
```

## LangGraph 对照

`experiments/langgraph/`：图编排与 checkpoint 对照实现，不参与 Core 依赖与 CI 主路径。

```bash
pip install -e ".[langgraph]"
python experiments/langgraph/demo_checkpoint_hitl.py
```

## 快速开始

```bash
pip install -e ".[test]"
cp .env.example .env
python -m react_agent "法国的首都是什么？"
```

Web 面板（实验）：`REACT_AGENT_EXPERIMENTAL_TOOLS=1` 后 `python -m react_agent.dashboard.server`。

## 评测（EVAL-ONLY）

文档排障四套离线门禁 + capability 规则打分：[`docs/DOCS_TROUBLESHOOT_EVAL.md`](docs/DOCS_TROUBLESHOOT_EVAL.md) · [`docs/EVAL_INDEX.md`](docs/EVAL_INDEX.md) · 证据地图：[`docs/P0_EVIDENCE_MAP.md`](docs/P0_EVIDENCE_MAP.md)。

```bash
python examples/eval/run_docs_troubleshoot_eval.py         # golden 34
python examples/eval/run_fault_eval.py                     # fault 12
python examples/eval/run_production_eval.py                # production 5
python examples/eval/run_git_docs_eval.py                  # git docs 5
python -m react_agent.eval --dataset capability
python examples/eval/run_execution_suite.py --publish
python examples/eval/run_public_benchmark.py              # GSM8K×10 + HotpotQA×10 offline
python examples/eval/run_public_rag_benchmark.py           # 分层 RAG：引用 by_tier + drop-off
# python examples/eval/run_public_benchmark.py --modes agent --publish  # 需 API Key
```

与 [llm-eval-engine](https://github.com/weihuaguo270-ops/llm-eval-engine) 校准口径：**held_out live κ≈0.69**（n=20，CI[0.46,0.92]）— 见 [METRICS_TRUST](https://github.com/weihuaguo270-ops/llm-eval-engine/blob/master/docs/METRICS_TRUST.md)；有效口径以该文档为准。  
失败归因：[trace-debugger FAILURE_INDEX](https://github.com/weihuaguo270-ops/trace-debugger/blob/master/docs/FAILURE_INDEX.md)。

### Harness 轨迹 Schema + 闭环 Demo

三仓共用 **Format B** 轨迹约定（1-based `step`，工具参数优先 `arguments` 字符串）：

| 产物 | 路径 |
|------|------|
| JSON Schema | [`schemas/harness_trajectory.schema.json`](schemas/harness_trajectory.schema.json) |
| 校验 / 归一化 | `react_agent.harness.schema` |
| 离线 fixture | `examples/fixtures/harness_closed_loop.json` |
| 一键 demo | `python examples/eval/harness_closed_loop.py` |

闭环：`Agent 记录 → Trace Debugger 失败分类 → Eval Engine Process Reward`（CI `integration` job 会 clone 两仓并跑 demo + **契约测试**）。

**跨仓集成验证：**

| 验证项 | 命令 / CI |
|--------|-----------|
| 跨仓评分 API | `pytest tests/test_eval_engine_contract.py` |
| Agent→Eval 路径 | `python tests/ci_verify_integration.py`（integration job） |
| Schema→tdebug→eval | `python examples/eval/harness_closed_loop.py --fixture` |

```bash
pip install -e ../trace-debugger -e ../llm-eval-engine   # 本地旁路仓
python examples/eval/harness_closed_loop.py --fixture
python examples/eval/harness_closed_loop.py --mock-agent
```

## 测试

```bash
# 离线单测（含 capability_scorer、resilience）
pytest tests/ -q

# 全模块脚本测试（不依赖 LLM）
python test_all.py

# 真实 LLM：CI 冒烟子集 / 全量（无 Key 时自动 skip）
pytest tests/test_real_llm.py -v -m real_llm_smoke
pytest tests/test_real_llm.py -v -m real_llm
```

### CI 与真实 LLM

| Job | 触发 | 行为 |
|-----|------|------|
| lint / test / integration | push、PR | 离线；不消耗 API |
| **Real LLM (smoke)** | push、PR（且已配置 Secret） | 跑 `real_llm_smoke`（事实问答 / 计算器 / 多步推理）；**失败会使该 job 红** |
| **Real LLM (full)** | Actions → Run workflow → suite=`full` | 全量 `real_llm` |

在仓库 **Settings → Secrets and variables → Actions** 添加 `DEEPSEEK_API_KEY`（与本地 `.env` 同名即可）。未配置时 **Real LLM gate** 会标记无 Key，smoke/full job 显示为 **Skipped**，不影响离线 CI。

也可本地写入 Secret（勿把 Key 提交进 Git）：

```bash
# 从 .env 读取一行写入 GitHub（需已 gh auth login）
gh secret set DEEPSEEK_API_KEY --repo weihuaguo270-ops/react-agent < <(grep '^DEEPSEEK_API_KEY=' .env | cut -d= -f2-)
```

仓库忽略本地 `llm_config.json`；CI / 新环境会回退到已提交的 [`llm_config.example.json`](llm_config.example.json)（Key 仍只来自环境变量 / Secret）。

## 环境要求

- Python 3.10+
- LLM API key（运行 Agent / 真实评测时需要）
- LangChain + LangGraph（可选）：`pip install -e ".[langgraph]"`，仅对照实验需要

## 相关项目

- [llm-eval-engine](https://github.com/weihuaguo270-ops/llm-eval-engine) — LLM 评估实验框架（Process Reward）
- [transformer-attention](https://github.com/weihuaguo270-ops/transformer-attention) — Attention 教学实现
- [trace-debugger](https://github.com/weihuaguo270-ops/trace-debugger) — 轨迹分析小工具

## Artifact 引用

Harness 轨迹支持 input_artifacts、output_artifacts 和步骤级 artifacts。
Recorder 只保留 id、media_type、uri 等白名单字段；Schema 校验禁止 data/base64
内嵌内容。该能力只记录媒体引用，不读取或评估媒体内容。

## License

MIT

## 贡献与安全

见 [CONTRIBUTING.md](CONTRIBUTING.md) / [SECURITY.md](SECURITY.md)。
