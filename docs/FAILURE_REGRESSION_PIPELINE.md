# 失败回归编排

目标口径：**失败自动检出 + 回归门禁 + 修复后强制复验**。

本页描述本仓编排入口；失败启发式在 `trace-debugger`，发布裁决在 `llm-eval-engine`。  
**禁止**在 sibling 缺失时静默跳过。

## 命令（P0 独立编排）

```powershell
pip install -e ".[test]"
pip install -e ../trace-debugger -e ../llm-eval-engine

# 绿路径：检出无回归，release=pass
python scripts/eval/failure/run_failure_regression_pipeline.py --mode pass --expect-decision pass

# 红路径：注入坏轨迹 + 业务态失败，release=hold
python scripts/eval/failure/run_failure_regression_pipeline.py --mode hold --expect-decision hold

# 修复后复验：关联父 run，要求改善到 pass
python scripts/eval/failure/run_failure_regression_pipeline.py `
  --mode pass --expect-decision pass `
  --reverify-from artifacts/failure-regression/<parent-hold-id>
```

## P1 默认挂载

共享模块：`react_agent.eval.failure_regression_gate`。

| 出口 | 默认行为 |
|------|----------|
| **GitHub Delivery** | `WorkflowConfig.failure_regression_gate=True`：验收测试后跑 Episode → failure-gate → release；`hold`/`review`/sibling 缺失则阻断成功（`failure_regression_hold` / `failure_regression_unavailable`），不为候选变更创建提交 |
| **SoftwareTaskRunner** | `SoftwareTaskRunnerConfig.failure_regression_gate=True`：公开/隐藏测试结果写出后调用 `attach_software_task_gate`；门禁未过则把 `succeeded` 降为 `failure_regression_hold` |

离线单测可显式设 `failure_regression_gate=False`；生产/CI 路径保持默认开启且 fail-closed。

## 产物

`artifacts/failure-regression/<run_id>/`（独立脚本）或 Delivery/SoftwareTask 各自 `runs/<id>/failure-regression/`：

| 文件 | 来源 |
|------|------|
| `trajectories/` | Format B 轨迹 |
| `baseline_scan.json` / `current_scan.json` | tdebug 扫描快照 |
| `failures.json` | failure-gate/v1 + `decision` |
| `findings.json` | Harness Health findings |
| `episodes/*.json` | evaluation-episode/v1 |
| `release.json` | eval-engine 发布裁决 |
| `pipeline_report.json` | 编排总览（含 reverify 链接） |

## SoftwareTask 验收（15764 / 15974 / 16253）

把已跑通的 FastAPI Agent 信封挂进**同一条** `failure_regression_gate` 流水线（失败则 fail-closed，禁止跳过）：

```powershell
python scripts/eval/failure/run_software_task_failure_regression.py `
  --out artifacts/failure-regression/software-tasks `
  --expect-all-pass-good
```

| 验收项 | 行为 |
|--------|------|
| **独立 JSON** | 每条任务写出与夹具同结构的 `release` / `findings` / `process_quality` / `repair_feedback` |
| **冻结 baseline** | 绿跑 seed → `frozen_baseline_scan.json`；坏补丁 → `hold`；好 Agent → `pass`（`baseline_source=provided`） |
| **复验剧本** | `reverify/parent-hold` → 好信封 `reverify_from` → 仅 `improved_to_pass` 放行 |
| **输入优先级** | 优先 `artifacts/software-tasks/runs/*-agent.json`；CI 回退 `fixtures/software_tasks/` |

总览：`artifacts/failure-regression/software-tasks/acceptance_summary.json`（claim：对齐工作流已在夹具 + 3 条 SoftwareTask 上复现）。

## CI

`.github/workflows/test.yml` 在安装依赖后**强制** clone/install 两仓，并执行：

- P0：pass + hold 断言与 `tests/test_failure_regression_pipeline.py`
- P1/P2：`tests/test_failure_regression_gate.py`（默认挂载 + 强制复验 + RepairLoop）
- A3–A5：过程质量非 stub、`tests/test_failure_regression_contracts.py`、[`FAILURE_REGRESSION_PITCH.md`](./FAILURE_REGRESSION_PITCH.md)
- SoftwareTask：`run_software_task_failure_regression.py` + `tests/test_software_task_failure_regression.py`（禁止跳过）

原 flywheel / StepWatcher 步骤不再 `skip if missing`；多行步骤须保留 `run: |`。

## P2 强制复验 + RepairLoop

| 能力 | 行为 |
|------|------|
| **hold 标注** | 门禁 hold/review 后写入 `reverify.required`；未 `improved_to_pass` 前不得当成功 |
| **跨 run 复验** | Delivery：`run(..., reverify_from=<parent failure-regression 目录>)`；SoftwareTask：`attach_software_task_gate(..., parent_run_dir=...)` |
| **同 run 修复** | 注入 `WorkflowConfig.repair_loop` 后：测试失败或门禁 hold 可自动 RepairLoop，再对 parent 做 `evaluate_forced_reverify` |
| **编排助手** | `run_gate_with_optional_repair`：initial hold → `repair_fn` → forced reverify |

```powershell
# 独立脚本复验（P0）
python scripts/eval/failure/run_failure_regression_pipeline.py `
  --mode pass --expect-decision pass `
  --reverify-from artifacts/failure-regression/<parent-hold-id>
```

成功口径：`reverify.improved_to_pass == true` 且 `release_decision == pass`。

## A3 过程质量（非 stub）

`build_process_quality`：用业务终态 / failure-gate / findings 算证据分，并尽量走
`ProcessRewardScorer` fast（确定性 judge，无 LLM）。产物 `process_quality.json`；
`metric` 为 `process_reward_fast+evidence_v1` 或降级 `failure_regression_evidence_v1`，
**禁止**再写死 `overall_score: 4.0` stub。

## A1 / A2（hold 信号驱动修复 + 真 baseline）

| 能力 | 行为 |
|------|------|
| **repair_feedback** | 门禁写出 `repair_feedback.json`（`repair-feedback/v1`），含 `planner_safe` 供 RepairLoop / 人工修复消费 |
| **Delivery 注入** | `repair_loop` 上下文带 `repair_feedback`；`ReActPatchPlanner` 读取该字段 |
| **真 baseline** | `failure_regression_baseline_scan`（Delivery / SoftwareTask）或 `--baseline-scan`；`baseline_source=provided` |
| **CI 对比** | 先绿跑落盘 baseline，再对同一 baseline 跑 green pass + red hold |

```powershell
# 冻结绿跑 baseline，再对比
python scripts/eval/failure/run_failure_regression_pipeline.py --mode pass --out artifacts/failure-regression/green
python scripts/eval/failure/run_failure_regression_pipeline.py --mode pass --baseline-scan artifacts/failure-regression/green/baseline_scan.json --expect-decision pass
python scripts/eval/failure/run_failure_regression_pipeline.py --mode hold --baseline-scan artifacts/failure-regression/green/baseline_scan.json --expect-decision hold
```

## 边界

- 本编排不自动修改 Agent；RepairLoop / 人工修复后必须再过强制复验。
- Delivery 报告字段 `failure_regression` / `repair` / `repair_feedback` 与 Episode 并列，供审计读取。
