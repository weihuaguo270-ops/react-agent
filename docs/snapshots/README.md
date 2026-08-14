# 冻结快照索引

本目录只保存可引用的评测证据，不保存日常运行轨迹。

## 当前证据

| 文件 | 用途 |
|---|---|
| `github_portfolio_dataset_20260813.json` | GitHub 只读业务任务数据集快照 |
| `execution_agent_snapshot_20260716_v3.json` | Execution Agent 当前冻结结果 |
| `public_benchmark_snapshot_agent_20260717.json` | 公开任务 Agent 路径结果 |
| `reliability_live_live_20260716_v2.json` | Live 可靠性复测 |
| `step_watcher_evidence_baseline.json` | StepWatcher 回归基线 |

## 历史对比

文件名中较早日期或 `v2` 之前的同名快照用于版本对比，不作为最新能力结论。引用历史结果时
必须同时写明日期、运行模式和模型配置。

`flywheel_closed_loop_20260716.json` 与 `tdebug_failure_flywheel_20260716.json`
是失败回流案例证据，应与当前发布门禁分开引用。

