# 公开评测报告索引

结构见 [`STRUCTURE.md`](STRUCTURE.md)。日期报告正文在 [`reports/`](reports/)；JSON 归档在 [`snapshots/`](snapshots/)。

本索引列出 **可复现** 的 Agent 评测快照（样本量有限，请按 n 与局限解读）。

## 报告一览

| 报告 | 数据集 | 结果 | 归档 JSON |
|------|--------|------|-----------|
| [capability_snapshot_20260713.md](./reports/capability_snapshot_20260713.md) | capability（当时 18 条） | 18/18（100%） | [snapshots/…](./snapshots/capability_snapshot_20260713.json) |
| [eval_report_20260713.md](./reports/eval_report_20260713.md) | default 功能集 26 条 | 23/26（88%） | 人工整理（见文内失败分析） |
| [capability_newcases_20260713.md](./reports/capability_newcases_20260713.md) | capability 扩容 6 条 | **5/6（83%）** | [snapshots/…](./snapshots/capability_newcases_20260713.json) |
| [execution_snapshot_20260715.md](./reports/execution_snapshot_20260715.md) | execution 离线工具集 8 条 | **8/8（100%）** | [snapshots/…](./snapshots/execution_snapshot_20260715.json) |
| [execution_agent_snapshot_20260715.md](./reports/execution_agent_snapshot_20260715.md) | execution **agent** 端到端 6 条 | **6/6（100%）** | DeepSeek；`REACT_AGENT_DISABLE_MCP=1`；[归档](./snapshots/execution_agent_snapshot_20260715.json) |
| [execution_agent_snapshot_20260715_v2.md](./reports/execution_agent_snapshot_20260715_v2.md) | agent 扩容 **24** 条（易/中/难各 8） | **24/24（100%）** | 含双工具/禁工具/算法；[归档](./snapshots/execution_agent_snapshot_20260715_v2.json) |
| [execution_agent_snapshot_20260716_v3.md](./reports/execution_agent_snapshot_20260716_v3.md) | agent 再扩至 **36** 条（易8/中12/难16） | **36/36（100%）** | [归档](./snapshots/execution_agent_snapshot_20260716_v3.json) |
| [reliability_snapshot_20260715.md](./reports/reliability_snapshot_20260715.md) | ToolGuard/自修注入对照 4 场景 | **4/4（100%）** | [snapshots/…](./snapshots/reliability_snapshot_20260715.json) |
| [reliability_live_live_20260716.md](./reports/reliability_live_live_20260716.md) | live Guard ON/OFF × 8 场景 | flaky 皆 6/6；**error_obs 0 vs 3** | [归档](./snapshots/reliability_live_live_20260716.json) |
| [reliability_live_live_20260716_v2.md](./reports/reliability_live_live_20260716_v2.md) | live 扩容 **20 flaky + 4 baseline** | flaky 20/20 vs 20/20；**error_obs 0 vs 3.1**；calls **1.0 vs 2.25** | [归档](./snapshots/reliability_live_live_20260716_v2.json) |
| [P0_EVIDENCE_MAP.md](./P0_EVIDENCE_MAP.md) | 四层证据串联 | — | Execution × Reliability × Failure × Judge |
| [daily_smoke/VARIANCE.md](./daily_smoke/VARIANCE.md) | 跨日 smoke | 自动追加 | Actions `daily-smoke`（UTC 01:00） |
| [FAILURE_FLYWHEEL.md](./FAILURE_FLYWHEEL.md) | 失败→动作→复测飞轮 | 真闭环已勾选 | 配合 tdebug 扫描 |
| [FAILURE_REGRESSION_PIPELINE.md](./FAILURE_REGRESSION_PIPELINE.md) | P0–P2 编排 + A1/A2 反馈与真 baseline；SoftwareTask 15764/15974/16253 同门禁验收 | CI 强制装两仓 + `run_software_task_failure_regression.py` | 不自动改 Agent；无 SLA |
| [FAILURE_REGRESSION_PITCH.md](./FAILURE_REGRESSION_PITCH.md) | 答辩三句话 + 一张图；可写「夹具 + 3 条 SoftwareTask」 | 产物链到 `artifacts/failure-regression/software-tasks/` | 口径页 |
| [SOFTWARE_TASK_RUNNER.md](./SOFTWARE_TASK_RUNNER.md) / [SOFTWARE_TASK_DATASET.md](./SOFTWARE_TASK_DATASET.md) | FastAPI 任务 Runner + 数据集 | 报告 [software_task_execution_20260913.md](./reports/software_task_execution_20260913.md) | Agent 成功率 ≠ 生产收益 |
| [PROJECT_CONTEXT.md](./PROJECT_CONTEXT.md) | 项目定位、对外口径与边界 | — | 背景总览 |
| [flywheel_closed_loop_20260716.md](./reports/flywheel_closed_loop_20260716.md) | 同批 100 条改前/改后 | **llm_offtrack 6→1** | [snapshots/…](./snapshots/flywheel_closed_loop_20260716.json) |
| 公开 RAG 子集（分层 v2） | HotpotQA-RAG smoke/hard/held_out | `examples/eval/run_public_rag_benchmark.py` | `public_rag_benchmark_subset.json` |
| GitHub 公开只读业务证据 | 仓库契约 + 当前公开 Issue | `examples/eval/run_github_business_tasks.py --repository <owner/repo>` | 2026-08-20 的两份快照**未随 main 归档**（只存在于侧分支 `backup/pre-split-wip`） |
| GitHub 公开只读交付样本 | agent-delivery-sandbox 公开 Issue（10 条） | 采集发生在 sibling 仓 `agent-delivery-sandbox` 侧 | 同上，未随 main 归档 |

当前 `capability_dataset.json` 已扩至 **24** 条（原 18 + 新 6）。全量重跑：

```bash
python examples/eval/publish_eval_snapshot.py --run capability --stem capability_snapshot_YYYYMMDD
```

## Execution 成功率

```bash
# 工具层（offline，CI 默认）
python examples/eval/run_execution_suite.py
# 端到端 Agent（需 API Key；评测默认关 MCP 以提高确定性）
set REACT_AGENT_DISABLE_MCP=1
python examples/eval/run_execution_suite.py --modes agent --publish
# 可按难度过滤：--difficulty easy,medium,hard
```

说明：`offline_tools`（现 12 条）与 `agent`（现 **36** 条，easy8/medium12/hard16）为不同指标，须分栏引用。

## 公开 RAG/Agent 子集（外部可比性 · 分层）

| tier | 含义 | 引用规则 |
|------|------|----------|
| `smoke` | 协议冒烟（易） | 不可单独代表 RAG 能力 |
| `hard` | 强干扰 + recall=1.0@k=2 | 主参考信号 |
| `held_out` | 设计后冻结 | 不对其调参 |

```bash
python examples/eval/run_public_rag_benchmark.py
python examples/eval/run_public_rag_benchmark.py --tiers hard,held_out --modes rag
```

数据集：`src/react_agent/eval/public_rag_benchmark_subset.json`。

## Harness 可靠性对照

```bash
python examples/eval/run_reliability_harness.py --publish
python examples/eval/run_reliability_live.py --mock
set REACT_AGENT_DISABLE_MCP=1
python examples/eval/run_reliability_live.py --live --publish
python examples/eval/run_failure_flywheel.py --fixture --publish
python examples/eval/run_flywheel_closed_loop.py --publish
```

证据总图见 [P0_EVIDENCE_MAP.md](./P0_EVIDENCE_MAP.md)。

## 失败归因周报

轨迹失败分布见姊妹仓 [trace-debugger/docs/FAILURE_INDEX.md](https://github.com/weihuaguo270-ops/trace-debugger/blob/master/docs/FAILURE_INDEX.md)。

## 快照发布

```bash
python examples/eval/publish_eval_snapshot.py --from-report src/react_agent/eval/reports/eval_XXXX.json
set REACT_AGENT_SKIP_RAG=1
python examples/eval/publish_eval_snapshot.py --run capability
python examples/eval/publish_eval_snapshot.py --run capability --only-new --stem capability_newcases_YYYYMMDD
```

## 与 llm-eval-engine 的分工

| 仓库 | 评测侧重 |
|------|----------|
| **react-agent** | 任务执行、领域验收、`EvaluationEpisode` 产出、基础规则指标 |
| **llm-eval-engine** | Episode 终态验证、Process Reward、动态 rubric、人机校准（κ） |

## 指标说明与限制

- 公开数字绑定具体 `report_id` / 归档 JSON；换模型后须重跑
- 角色类功能用例曾因 `must_contain` 过严出现假阴性（见功能报告）
- 一致性用例会多次调用 LLM，费用与耗时更高
- **公开 RAG**：须引用 `by_tier` 与 drop-off；smoke 100% 不能单独代表能力
