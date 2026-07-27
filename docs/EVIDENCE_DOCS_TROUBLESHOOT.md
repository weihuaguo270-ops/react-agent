# 证据化文档排障（主场景说明）

本页写 **docs_troubleshoot** 现在能做什么、不能说什么、接下来补什么。评测命令和门禁见 [`DOCS_TROUBLESHOOT_EVAL.md`](DOCS_TROUBLESHOOT_EVAL.md)。

## 两层定位

| | 当前（已实现） | 目标（下一阶段） |
|--|----------------|------------------|
| **一句话** | 有证据约束的文档 / Runbook 问答后端 | 能收集现场证据、验证假设并给出可执行步骤的 API 故障诊断 Agent |
| **输入** | 用户自然语言问题 + 内部语料索引 | 问题 + 真实资料源 + 错误响应 / 日志 / Trace / 配置快照 |
| **输出** | 带引用的答案，或「依据不足」拒答 | 结构化诊断：现象、候选原因、证据、验证动作、修复步骤、风险与升级条件 |
| **评测** | 34 条分层黄金集（关键词 + 引用 + 拒答） | 真实历史故障盲测：根因命中率、错误建议率、证据充分率、MTTR、正确升级率 |

**对外名称建议收敛为「证据化文档排障」**；避免单独使用「API 排障 Agent」，以免用户期待自动定位根因。

## 为什么选这个主场景

Core 里检索、工具调用、权限闸门、Harness 轨迹本来就在——拿来做文档 / Runbook 问答，比另搭一个泛 Agent 框架省事。

另外有三样东西能离线验收：

1. 固定语料（`corpus/` 14 篇）和 **34 条黄金集**，改代码跑 eval 就知道有没有回退。
2. 引用 / 拒答策略写死在 Workflow 里，比开放聊天好判对错。
3. v0.3 补了现场证据输入和 `diagnosis` schema，fault / production / git 三套 eval 也能挂 CI——但规则 + 检索为主，**不是**自动定根因。

对外名称用「证据化文档排障」。单独叫「API 排障 Agent」容易让人以为能读线上日志自动定位——目前做不到。

## 当前边界（须如实表述）

### 工作流实质

默认路径为 **检索 → 句级要点合成 → 引用 / 拒答策略**（`synthesize.py` + `draft.py` + `policy.py`），诊断步骤由 `cause_rules.py` / `diagnosis.py` 结构化输出，不是开放式多轮根因推理。

### 起草能力

`synthesize.py` 从命中结果抽取与问题相关的句子并标注来源；`cause_rules.py` 将现场 HTTP 错误映射为候选原因与修复步骤。**不会**在无文档/证据支撑时臆造根因。

### 检索与语料

- 当前语料为 **14 篇** 内置 md；排序含针对固定问法的 domain boost。
- 在黄金集上表现好，**不能**等同证明对真实企业文档库、OpenAPI 全量或多版本混部有效。

### 未接入 / 未自动采集的现场证据

当前**不会自动抓取**线上流量，但 Workflow **支持**调用方传入：

- HTTP 错误 JSON + 状态码（`error_response`）
- 请求头（脱敏，`request_headers`）
- **日志片段**（`log_excerpt`）与 **Trace JSON**（`trace_context`）
- 配置快照（`read_config_snapshot`）、健康探测（`probe_service_health`）

仍**不读取**：未传入的应用日志流、分布式 Trace 后端、自动 OpenAPI 拉取（需 `REACT_AGENT_INGEST_OPENAPI=1` 与 spec 路径）。

## 下一阶段主线：三个闭环

通用 Agent 能力（多 Agent、ToT、Dashboard 等）保持实验态，不扩主场景叙事。接下来主要补这三块（v0.3 已有一版，见下表）：

### 实现状态（2026-07）

| 闭环 | 状态 | 入口 |
|------|------|------|
| ① 真实资料 | **增强** | 递归 ingest + Git · **生产盲测语料** `fixtures/.../production_corpus` |
| ② 现场证据 | **增强** | error / headers / log / trace / **Trace MCP** / config / health |
| ③ 结构化诊断 | **增强** | `cause_infer` + **`fix_policy` 权限闸门**（`pending_fix_steps`） |
| 评测 | **增强** | golden 34 · fault 12 · production 5 · **git docs 5** |

### 1. 接入真实资料

| 能力 | 说明 |
|------|------|
| 目录 / Git 仓库 ingest | 替代仅 `corpus/*.md` 静态包 |
| OpenAPI / 版本元数据 | 端点、错误码、Sunset 与文档对齐 |
| 增量索引 | 文档变更可追踪、可回归 |

### 2. 接入现场证据

| 证据类型 | 用途 |
|----------|------|
| 错误响应 JSON + HTTP 状态 | 与语料错误码表对照 |
| 请求头（脱敏） | Bearer / Request-Id 等 |
| 日志片段 + Trace ID | 关联 runbook 排查链 |
| 配置快照 | 环境变量、功能开关 |
| 健康检查 | `/health` 等探测结果作为事实输入 |

### 3. 输出结构化诊断

目标 schema（示意）：

```yaml
phenomenon:        # 用户可见现象
candidate_causes:  # 排序后的候选原因
evidence:          # 每条原因绑定的文档或现场证据
verify_actions:    # 建议验证步骤（只读优先）
fix_steps:         # 可执行修复（须过权限闸门）
risks:             # 误操作风险
escalation:        # 何时升级、找谁
citations:         # 文档引用（保留现有约束）
```

Workflow 版本演进：`docs_troubleshoot` v3+ 在保留引用 / 拒答 policy 的前提下，增加 evidence 输入 step 与结构化 final。

## 评测演进

| 阶段 | 指标 | 数据集 |
|------|------|--------|
| **现在** | pass_rate、by_tag、引用命中、拒答正确 | `golden.json` 34 条 + leakage guards |
| **仿真故障** | 答案 + `diagnosis` + 根因/禁词指标 | `fault_cases.json` 12 条 · `run_fault_eval.py` |
| **生产盲测** | 仅外部 ingest 语料可答 | `production_cases.json` 5 条 · `run_production_eval.py` |
| **下一阶** | 根因命中率、错误建议率、证据充分率 | 真实 / 仿真历史故障盲测集（held_out 冻结） |
| **运营** | 平均解决时间、正确升级率 | 脱敏工单回放（需单独治理） |

黄金集仍作 **回归门禁**；新指标在新数据集上分栏报告，不与 keyword 命中率混谈。

## 与运行时其他能力的关系

| 模块 | 主场景阶段 |
|------|------------|
| Workflow + 引用 policy | **当前交付核心** |
| ReAct + ToolGuard + Harness | 探索路径；为诊断闭环提供执行与轨迹 |
| 权限闸门 | 修复步骤、健康检查、读配置均须走 gate |
| capability / execution / public RAG | 通用能力轨，**非**下一阶段扩张重点 |
| LangGraph / 多 Agent | 实验对照，非默认叙事 |

## 相关文档

- 架构：[`CORE_ARCHITECTURE.md`](CORE_ARCHITECTURE.md)
- 工作流入口：[`AGENT_WORKFLOW.md`](AGENT_WORKFLOW.md)
- 黄金集评测：[`DOCS_TROUBLESHOOT_EVAL.md`](DOCS_TROUBLESHOOT_EVAL.md)
- 成熟度矩阵：[`PRODUCTION_MATURITY.md`](PRODUCTION_MATURITY.md)
