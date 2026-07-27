# ReAct Agent

[![CI](https://github.com/weihuaguo270-ops/react-agent/actions/workflows/test.yml/badge.svg)](https://github.com/weihuaguo270-ops/react-agent/actions/workflows/test.yml) [![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org) [![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE) [![scope](https://img.shields.io/badge/定位-证据化文档排障-lightgrey)](docs/EVIDENCE_DOCS_TROUBLESHOOT.md)

个人维护的 Agent 运行时原型。默认入口是 `docs_troubleshoot` Workflow；探索路径是 `react_loop` + Harness 轨迹（Format B JSON）。

**主场景**：[证据化文档排障](docs/EVIDENCE_DOCS_TROUBLESHOOT.md) — 内部文档 / Runbook 问答，能引用就引用、没依据就拒答（**不是**自动 API 根因诊断）。v0.3 起可传入 HTTP 错误、日志、Trace，并输出结构化 `diagnosis`；底层仍是检索 + 规则，不是多轮推理 Agent。

结构：[`docs/STRUCTURE.md`](docs/STRUCTURE.md) · 架构：[`docs/CORE_ARCHITECTURE.md`](docs/CORE_ARCHITECTURE.md) · 成熟度：[`docs/PRODUCTION_MATURITY.md`](docs/PRODUCTION_MATURITY.md)。

## 主场景：证据化文档排障

```bash
set REACT_AGENT_APP=docs_troubleshoot
set REACT_AGENT_RAG_MODE=keyword
python examples/demos/demo_workflow.py                   # 确定性 Workflow（默认入口）
python -m react_agent.workflow run docs_troubleshoot --query "401 返回什么？"
python examples/eval/run_docs_troubleshoot_eval.py      # 黄金集 34 条
python examples/eval/run_fault_eval.py                  # 故障模拟 12 条
python examples/eval/run_production_eval.py             # 生产盲测 5 条
python examples/eval/run_git_docs_eval.py               # Git 文档 held-out 5 条
python -m react_agent.server --port 8765           # /health /v1/chat /v1/workflows
```

Workflow v5：`现场证据 → search → lookup_api → synthesize（句级要点）→ policy（引用/拒答）→ diagnosis`。详见 [`EVIDENCE_DOCS_TROUBLESHOOT.md`](docs/EVIDENCE_DOCS_TROUBLESHOOT.md) · 评测：[`DOCS_TROUBLESHOOT_EVAL.md`](docs/DOCS_TROUBLESHOOT_EVAL.md) · **Since v0.3.0**。

## 范围与定位

| 是 | 不是 |
|----|------|
| 证据化文档 / Runbook 问答（引用 + 拒答 + 四套离线 eval） | 自动 API 根因诊断 Agent（无证据不臆造根因） |
| 现场证据 + 结构化 diagnosis（HTTP / log / trace；fix_steps 权限闸门） | 多租户 Agent 平台 |
| 自建 Core（Workflow + ReAct + 权限/Harness）可服务化、可回归 | 以 LangGraph 为默认实现 |
| 确定性工作流 + 分层评测（golden / fault / production / git） | 企业级全量 Git / OpenAPI 生产 ingest |

跨仓：**本仓 Core** = 执行 + capability 规则打分；**llm-eval-engine** = Process Reward / 人机校准；**trace-debugger** = 轨迹启发式复盘。共享约定见 [`schemas/harness_trajectory.schema.json`](schemas/harness_trajectory.schema.json)。

证据地图：[`docs/P0_EVIDENCE_MAP.md`](docs/P0_EVIDENCE_MAP.md)。

## 架构概览

```
query
  ├─ Workflow（确定性：docs_troubleshoot）     ← 默认路径
  └─ react_loop（自由 ReAct + 工具）
        → permission gate → tools / ToolGuard
        → CONTEXT.manage → Format B 轨迹
```

| 维度 | Core（默认） |
|------|----------------|
| **入口** | `react_loop()` / `run_workflow()` / `python -m react_agent.server` |
| **依赖** | 标准库 + LLM API（Workflow 离线可不需 Key） |
| **侧重点** | 控制流透明、Workflow、Harness、评测证据 |

### 执行流程（Core）

```
query
  ├─ run_workflow("docs_troubleshoot")     ← 确定性路径（黄金集同此）
  │     证据 → search → lookup_api → synthesize → policy → diagnosis
  └─ react_loop()                          ← 自由探索
          ├── system prompt / LLM
          ├── 工具（含 list/run_workflow）
          └── Format B 轨迹
```

多 Agent / MCP / RAG / LangGraph 为实验能力，见 [`docs/EXPERIMENTAL.md`](docs/EXPERIMENTAL.md)。

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
| 进程沙箱 | `harness/sandbox.py` | 子进程 + 超时，降低崩溃拖死主循环的概率 |

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
- 权限层 **不是** OS ACL；未知工具名默认不 DENY。
- 沙箱 **不是** 容器/seccomp；`execute_python` 仍可能访问本机权限内资源。
- 危险 shell 字符串（如 `rm -rf`）**不会**被逐字解析拦截；请勿对不可信代码开放执行工具。

`harness/sandbox.py` 支持 `off` / `auto` / `on`；子进程内禁止再次预热沙箱，避免递归拉起进程。

### 执行轨迹（Harness）

每步 thought / action / observation 写入 Format B JSON，供回放和跨仓对接（`harness/recorder.py` → `schemas/harness_trajectory.schema.json`）。

```python
from react_agent.harness.recorder import current_trajectory

result = react_loop("分析这份数据")
trajectory = current_trajectory()

# 逐步骤回放
from react_agent.harness.replay import replay_trajectory
replay_trajectory(trajectory)
```

### RAG / MCP / Context / 业务 Demo

主场景见上文「证据化文档排障」。实验模块与工作流总览：[`docs/AGENT_WORKFLOW.md`](docs/AGENT_WORKFLOW.md)、[`docs/EXPERIMENTAL.md`](docs/EXPERIMENTAL.md)。

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

## License

MIT

## 贡献与安全

见 [CONTRIBUTING.md](CONTRIBUTING.md) / [SECURITY.md](SECURITY.md)。
