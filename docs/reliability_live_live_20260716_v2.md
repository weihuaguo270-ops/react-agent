# Live Harness 可靠性对照扩容（reliability_live_live_20260716_v2）

- **report_id:** `reliability_live_live_20260716_v2`
- **timestamp:** `2026-07-16T01:20:53.065266+00:00`
- **mode:** `live`
- **git:** `98817ff`


> 扩容版：20 flaky + 4 baseline；主看 error_obs / tool_calls 对照。
## 核心对照（诱导 flaky 子集）

| setting | passed | total | pass_rate | mean_error_obs | mean_tool_calls | self_repair_rate |
|---------|-------:|------:|----------:|---------------:|----------------:|-----------------:|
| Guard+自修 **ON** | 20 | 20 | **100.0%** | 0.0 | 1.0 | 0.0% |
| Guard+自修 **OFF** | 20 | 20 | **100.0%** | 3.1 | 2.25 | 0.0% |

- ON 独过（OFF 失败）场景数: **0/20**

> 若两侧通过率接近，仍应看 **mean_error_obs / mean_tool_calls**：
> Guard ON 通常把重试留在工具层，LLM 侧错误观测更少、调用轮次更短。

## 基线（无 flaky 注入）

- ON: 4/4 (100.0%)
- OFF: 4/4 (100.0%)

## 逐场景

| id | kind | inject | ON | OFF | on_better |
|----|------|--------|:--:|:---:|:---------:|
| `live_flaky_calc_17x19` | flaky | `calculator:2` | Y | Y | - |
| `live_flaky_calc_8x7` | flaky | `calculator:2` | Y | Y | - |
| `live_flaky_calc_15x16` | flaky | `calculator:2` | Y | Y | - |
| `live_flaky_calc_12x12` | flaky | `calculator:2` | Y | Y | - |
| `live_flaky_calc_9x9` | flaky | `calculator:2` | Y | Y | - |
| `live_flaky_calc_25x4` | flaky | `calculator:2` | Y | Y | - |
| `live_flaky_calc_33x3` | flaky | `calculator:2` | Y | Y | - |
| `live_flaky_calc_48_div_6` | flaky | `calculator:2` | Y | Y | - |
| `live_flaky_calc_7x8` | flaky | `calculator:2` | Y | Y | - |
| `live_flaky_calc_21x5` | flaky | `calculator:2` | Y | Y | - |
| `live_flaky_calc_13x14` | flaky | `calculator:2` | Y | Y | - |
| `live_flaky_calc_16x16` | flaky | `calculator:2` | Y | Y | - |
| `live_flaky_py_fact5` | flaky | `execute_python:1` | Y | Y | - |
| `live_flaky_py_sum` | flaky | `execute_python:1` | Y | Y | - |
| `live_flaky_py_pow` | flaky | `execute_python:1` | Y | Y | - |
| `live_flaky_py_fact4` | flaky | `execute_python:1` | Y | Y | - |
| `live_flaky_py_sum10` | flaky | `execute_python:1` | Y | Y | - |
| `live_flaky_py_pow3` | flaky | `execute_python:1` | Y | Y | - |
| `live_flaky_py_len` | flaky | `execute_python:1` | Y | Y | - |
| `live_flaky_py_abs` | flaky | `execute_python:1` | Y | Y | - |
| `live_baseline_calc` | baseline | `-` | Y | Y | - |
| `live_baseline_time_calc` | baseline | `-` | Y | Y | - |
| `live_baseline_py_sum` | baseline | `-` | Y | Y | - |
| `live_baseline_calc_99` | baseline | `-` | Y | Y | - |

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
