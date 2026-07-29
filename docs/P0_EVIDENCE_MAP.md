# P0 证据地图（Execution × Reliability × Failure × Judge）

四层证据放在一页，方便对照引用。数字截至 2026-07-15/16；**分栏报，不要合成一个总分**。

| 层 | 问题 | 证据 | 数字（截至 2026-07-15/16） |
|----|------|------|---------------------------|
| **能不能干成** | 工具 / Agent 任务成功率 | [execution offline](./execution_snapshot_20260715.md) · [agent v3](./execution_agent_snapshot_20260716_v3.md) | offline **12/12**；agent **36/36**（易8/中12/难16） |
| **坏了能不能撑住** | Guard/自修是否有效 | [注入对照](./reliability_snapshot_20260715.md) · [live v2](./reliability_live_live_20260716_v2.md) | 注入 **4/4**；live flaky **n=20**：ON/OFF 皆 100%，**error_obs 0 vs 3.1**，**tool_calls 1.0 vs 2.25** |
| **坏在哪** | 轨迹失败分布 | [tdebug 真实 100 条](https://github.com/weihuaguo270-ops/trace-debugger/blob/master/docs/tdebug_failure_real_20260715.md) · [黄金集 27 条](https://github.com/weihuaguo270-ops/trace-debugger/blob/master/docs/golden_evidence_baseline.md) · [StepWatcher 跨仓](./step_watcher_evidence_baseline.md) · [飞轮闭环](./flywheel_closed_loop_20260716.md) | golden **27/27**；StepWatcher **6/6**；同批重扫 offtrack **6→1** |
| **评得清不清** | Judge 与人标一致吗 | [κ offline](https://github.com/weihuaguo270-ops/llm-eval-engine/blob/master/docs/calibration_snapshot_20260716_offline.md) · [κ live](https://github.com/weihuaguo270-ops/llm-eval-engine/blob/master/docs/calibration_snapshot_20260716_live.md) · [怎么读](https://github.com/weihuaguo270-ops/llm-eval-engine/blob/master/docs/METRICS_TRUST.md) | **held_out live** κ≈**0.69**（n=20，CI[0.46,0.92]）；全量 live ≈0.67；offline held_out=1.0（n=20，冻结） |

## 引用顺序

1. **Agent 开发**：execution **36/36** + live reliability ON/OFF 表 → tdebug 失败分布与飞轮闭环  
2. **评测**：κ 校准 + tdebug 失败 taxonomy → execution 作为「任务通过率」另一轨  
3. **分栏**：offline、agent、Judge 分属不同指标，不可合并为一个数字

## 一键复跑

```bash
# Execution
python examples/eval/run_execution_suite.py
set REACT_AGENT_DISABLE_MCP=1
python examples/eval/run_execution_suite.py --modes agent --publish

# Reliability
python examples/eval/run_reliability_harness.py --publish
python examples/eval/run_reliability_live.py --mock
python examples/eval/run_reliability_live.py --live --publish

# Failure flywheel（观察→修复→同批对照）
python examples/eval/run_failure_flywheel.py --fixture --publish
python examples/eval/run_flywheel_closed_loop.py --publish

# StepWatcher 跨仓证据（需 sibling trace-debugger）
python examples/eval/run_step_watcher_evidence.py --publish
python -m pytest tests/test_step_watcher_golden_e2e.py -v

# 跨日 variance（P0 软尾；GitHub Actions 每天 UTC 01:00 ≈ 北京 09:00）
python examples/eval/run_daily_smoke.py
# 表：docs/daily_smoke/VARIANCE.md
```

## 指标限制

- 样本量属学习级；live 结果绑定模型与日期  
- flaky live 使用注入超时，验证机制有效，不等于生产故障率  
- κ：held_out live 优先；live 与 offline 分栏；单人标注、第二标注者 protocol_ready  
- execution 报告含 Wilson 95% CI 与 tool/final 分项率，须与 headline 一并引用  
- 飞轮 `llm_offtrack` 下降含假阳性修复；`duplicate` 历史 traj 不变，需新跑才体现 Harness 拦截
- **跨日 variance**：见 [`daily_smoke/VARIANCE.md`](./daily_smoke/VARIANCE.md)（workflow `daily-smoke`）；单日大快照仍看上表
