# Business Pilot Execution Record

日期：2026-08-20

## 已执行

```text
python examples/eval/run_business_pilot.py --source expense
python examples/eval/run_expense_business_eval.py --agent-version expense-reference-v1 --profile reference
python examples/eval/run_expense_business_eval.py --agent-version expense-no-action-v0 --profile no_action --compare-reference
python examples/eval/run_github_portfolio_dataset.py --cache-dir .tmp/github-cache-20260820
```

结果：

- 费用参考版本：8 个任务全部通过，三个 split 均有样本；状态断言和审计事件数均通过。
- 费用 `no_action`：8 个任务全部失败，baseline 失败原因是台账保持 `pending`、没有决策码、审计事件数为 0；逐用例比较输出 `hold`。
- GitHub 组合集：10 个公开仓库、50 条只读元数据任务，dev/golden/held_out 为 15/20/15，来源可追溯，完成门禁通过。
- 代码回归：`225 passed, 4 skipped`；Sandbox 安全专测 `17 passed`。
- Sandbox 运行时探测：Podman machine `podman-machine-default` 为 running，真实 live-check `23/23` 通过；证据见 `docs/snapshots/sandbox_live_check_latest.json`。

快照：

- `docs/snapshots/business_pilot_expense_20260820.json`
- `docs/snapshots/expense_reference_20260820.json`
- `docs/snapshots/expense_no_action_20260820.json`
- `docs/snapshots/github_portfolio_dataset_20260820.json`

## 边界

费用数据是仓库内受控业务夹具；`no_action` 是故障注入，不是历史生产 Agent。GitHub 数据来自公开 REST API，只读且内容会变化，不等价于生产工单或行业 benchmark。报告中的 `accepted`/`resolved` 仅在夹具已经提供这些字段时成立，不能替代独立人工复核和业务系统最终状态。

真实脱敏任务、真实旧版本 baseline、独立人工复核和持续多版本线上对比仍待外部数据授权后执行。Sandbox live-check 已完成，但仍不替代逃逸测试、镜像供应链审计和多租户安全评审。
