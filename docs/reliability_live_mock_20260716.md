# Live Harness 可靠性对照（reliability_live_mock_20260716）

- **report_id:** `reliability_live_20260716_005430`
- **timestamp:** `2026-07-16T00:54:30.613962+00:00`
- **mode:** `mock`
- **git:** `98817ff`

## 核心对照（诱导 flaky 子集）

| setting | passed | total | pass_rate | mean_error_obs | mean_tool_calls | self_repair_rate |
|---------|-------:|------:|----------:|---------------:|----------------:|-----------------:|
| Guard+自修 **ON** | 6 | 6 | **100.0%** | 0.0 | 1.0 | 0.0% |
| Guard+自修 **OFF** | 0 | 6 | **0.0%** | 3.0 | 1.0 | 100.0% |

- ON 独过（OFF 失败）场景数: **6/6**

## 基线（无 flaky 注入）

- ON: 2/2 (100.0%)
- OFF: 2/2 (100.0%)

## 逐场景

| id | kind | inject | ON | OFF | on_better |
|----|------|--------|:--:|:---:|:---------:|
| `live_flaky_calc_17x19` | flaky | `calculator:2` | Y | N | Y |
| `live_flaky_calc_8x7` | flaky | `calculator:2` | Y | N | Y |
| `live_flaky_calc_15x16` | flaky | `calculator:2` | Y | N | Y |
| `live_flaky_py_fact5` | flaky | `execute_python:1` | Y | N | Y |
| `live_flaky_py_sum` | flaky | `execute_python:1` | Y | N | Y |
| `live_flaky_py_pow` | flaky | `execute_python:1` | Y | N | Y |
| `live_baseline_calc` | baseline | `-` | Y | Y | - |
| `live_baseline_time_calc` | baseline | `-` | Y | Y | - |

## 复现

```bash
python examples/run_reliability_live.py --mock
set REACT_AGENT_DISABLE_MCP=1
python examples/run_reliability_live.py --live --publish
```

## 诚实边界

- flaky 由 `REACT_AGENT_INJECT_FLAKY` **注入超时异常**，用于对照 ToolGuard 重试；不是线上随机故障采样
- live 绑定具体模型与日期；样本量 8 场景 × 2 设置，属学习级证据
- 与注入单元表（`reliability_snapshot_*`）互补：本报告含 **LLM 闭环**
