# ReAct Agent

[![CI](https://github.com/weihuaguo270-ops/react-agent/actions/workflows/test.yml/badge.svg)](https://github.com/weihuaguo270-ops/react-agent/actions/workflows/test.yml) [![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org) [![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE) [![learning](https://img.shields.io/badge/status-learning%20%2F%20not%20production-lightgrey)](docs/EXPERIMENTAL.md)

**学习向 Agent 运行时** — 把 ReAct 控制流、工具调用、轨迹（Format B）、学习级权限与 ToolGuard 做成可跑、可测、可复盘的参考实现；并用 LangGraph 对照理解框架编排。  
可选能力（RAG / MCP / 多 Agent）与评测证据见下方链接，**默认叙事以 Core 路径 + 证据链为准**。

## 范围与定位

| 是 | 不是 |
|----|------|
| 弄清 Agent 怎么跑：循环、工具、失败与观测 | 生产级 Agent 平台或安全产品 |
| Core 与 LangGraph 两条路径可对照 | 「只会手写」或「只会调框架」 |
| 离线 CI + 可选真实 LLM 冒烟 | 微服务切分 / SLA / 不可信代码隔离保证 |

跨仓：**本仓 Core** = 执行 + capability 规则打分；**llm-eval-engine** = Process Reward / 人机校准；**trace-debugger** = 轨迹启发式复盘。共享约定见 [`schemas/harness_trajectory.schema.json`](schemas/harness_trajectory.schema.json)。

求职/证据地图（与运行时功能分开）：[`docs/P0_EVIDENCE_MAP.md`](docs/P0_EVIDENCE_MAP.md)。

## 架构概览

理解 Agent 运行时不止一种方式：本仓库用 **过程式参考实现（Core）** 看清控制流，用 **LangGraph 对照** 看清图编排 / checkpoint；两者共享轨迹约定，不追求逐步行为等价。

| 维度 | Core（`src/react_agent/`） | LangGraph（`experiments/langgraph/`） |
|------|---------------------------|--------------------------------------|
| **入口** | `react_loop()` | StateGraph + `MemorySaver` |
| **依赖** | 标准库 + LLM API | 可选 `[langgraph]` extras |
| **侧重点** | 控制流透明、Harness / ToolGuard 深耦合 | 图边、续跑、团队常见编排模型 |
| **关系** | 默认演示与评测主路径 | 对照实验（见 Demo） |

### 执行流程（Core）

```
query → react_loop()
          ├── system prompt（角色 / CoT）
          ├── LLM → thought / action
          ├── 工具执行（权限提示 + ToolGuard）
          └── 观测回填 → 直至最终答案
```

多 Agent / MCP / RAG：**可选**，见 [`docs/EXPERIMENTAL.md`](docs/EXPERIMENTAL.md)。

### 模块清单

```
react_agent/                    # CORE
├── react_loop.py               ReAct 循环
├── llm.py / prompts.py / cot.py
├── tools/                      默认工具（计算/搜索/抓取/摘要/时间/执行）
├── context.py / memory.py
├── harness/                    录制 · 回放 · Schema · 沙箱超时
├── safety/                     学习级权限提示 + HITL
├── resilience.py               ToolGuard（超时/重试；非安全边界）
└── eval/                       EVAL-ONLY：capability 规则打分

# EXPERIMENTAL（默认不注册进工具表）— 见 docs/EXPERIMENTAL.md
#   rag.py · mcp_*.py · orchestrator.py · tot.py · dashboard/
#   experiments/langgraph/
```

## 核心功能

### 多 Provider LLM 支持

优先读取项目根目录 `.env` / `llm_config.json`（`.env` 会覆盖系统里残留的旧 API Key），也可用环境变量切换 provider：

```bash
export LLM_PROVIDER=deepseek   # 或 openai / anthropic
```

### 权限与沙箱（学习级，非生产隔离）

工具调用采用 **名称表 + 可选参数规则** 的四级提示策略（`safety/permissions.py`）：

| 等级 | 行为 | 适用场景（示例） |
|------|------|------------------|
| SAFE | 自动放行 | web_search、calculator |
| NOTIFY | 记录后继续 | 部分读信息工具 |
| CONFIRM | 询问用户 | write_file、execute_python |
| DENY | 默认拦截 | 表内登记的破坏性工具名 |

说明（诚实边界）：
- **不是** OS / 容器级沙箱；未知工具名默认不在 DENY 表内。
- `execute_python` / `harness/sandbox` 主要是 **子进程 + 超时**，用于隔离崩溃与卡住，**不能**当作安全边界（代码仍可访问本机网络/文件权限范围内资源）。
- 危险 shell 字符串（如 `rm -rf`）**不会**被逐字解析拦截；请勿用生产不可信代码跑本项目的执行工具。

`harness/sandbox.py` 支持 `off` / `auto` / `on`；子进程内禁止再次预热沙箱，避免递归拉起进程。

### 执行轨迹录制

完整录制每步 thought/action/observation，支持事后分析和回放：

```python
from react_agent.harness.recorder import current_trajectory

result = react_loop("分析这份数据")
trajectory = current_trajectory()

# 逐步骤回放
from react_agent.harness.replay import replay_trajectory
replay_trajectory(trajectory)
```

### RAG / MCP / 多 Agent（实验）

默认关闭。详见 [`docs/EXPERIMENTAL.md`](docs/EXPERIMENTAL.md)。

```bash
set REACT_AGENT_EXPERIMENTAL_TOOLS=1   # 注册 rag_query / tot / dashboard
pip install -e ".[rag]"                # 语义检索依赖
# MCP：cp mcp_servers.example.json mcp_servers.json 或 --mcp ...
```

## LangGraph 对照（`experiments/langgraph/`）

用框架路径对照 Core：图编排、checkpoint、HITL gate。  
不与 Core 做严格行为等价；轨迹侧对齐 **Harness Format B**。

- 无 Key Demo（StateGraph + Checkpoint + HITL）:

```bash
pip install -e ".[langgraph]"
python experiments/langgraph/demo_checkpoint_hitl.py
pytest tests/test_langgraph_harness_contract.py -q
```

## 快速开始

```bash
pip install -e ".[test]"
cp .env.example .env
python -m react_agent "法国的首都是什么？"
```

Web 面板（实验）：`REACT_AGENT_EXPERIMENTAL_TOOLS=1` 后 `python -m react_agent.dashboard.server`。

## 评测（EVAL-ONLY）

能力规则打分与公开快照索引：[`docs/EVAL_INDEX.md`](docs/EVAL_INDEX.md) · 证据地图：[`docs/P0_EVIDENCE_MAP.md`](docs/P0_EVIDENCE_MAP.md)。

```bash
python -m react_agent.eval --dataset capability
python examples/run_execution_suite.py --publish
python examples/run_public_benchmark.py              # GSM8K×10 + HotpotQA×10 offline
# python examples/run_public_benchmark.py --modes agent --publish  # 需 API Key
```

与 [llm-eval-engine](https://github.com/weihuaguo270-ops/llm-eval-engine) 校准口径：**held_out live κ≈0.69**（n=20，CI[0.46,0.92]）— 见 [METRICS_TRUST](https://github.com/weihuaguo270-ops/llm-eval-engine/blob/master/docs/METRICS_TRUST.md)，勿引用旧 n=15/κ≈0.47 或扩容前 n=11/κ≈0.59。  
失败归因：[trace-debugger FAILURE_INDEX](https://github.com/weihuaguo270-ops/trace-debugger/blob/master/docs/FAILURE_INDEX.md)。

### Harness 轨迹 Schema + 闭环 Demo

三仓共用 **Format B** 轨迹约定（1-based `step`，工具参数优先 `arguments` 字符串）：

| 产物 | 路径 |
|------|------|
| JSON Schema | [`schemas/harness_trajectory.schema.json`](schemas/harness_trajectory.schema.json) |
| 校验 / 归一化 | `react_agent.harness.schema` |
| 离线 fixture | `examples/fixtures/harness_closed_loop.json` |
| 一键 demo | `python examples/harness_closed_loop.py` |

闭环：`Agent 记录 → Trace Debugger 失败分类 → Eval Engine Process Reward`（CI `integration` job 会 clone 两仓并跑 demo + **契约测试**）。

**可信度绑定（勿口头宣称「已打通」而无测试）：**

| 验证 | 命令 / CI |
|------|-----------|
| 跨仓评分 API | `pytest tests/test_eval_engine_contract.py` |
| Agent→Eval 路径 | `python tests/ci_verify_integration.py`（integration job） |
| Schema→tdebug→eval | `python examples/harness_closed_loop.py --fixture` |

```bash
pip install -e ../trace-debugger -e ../llm-eval-engine   # 本地旁路仓
python examples/harness_closed_loop.py --fixture
python examples/harness_closed_loop.py --mock-agent
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
