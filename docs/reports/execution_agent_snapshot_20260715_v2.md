# Execution Agent 扩容快照（execution_agent_snapshot_20260715_v2）

- git: `8ede276`
- archived_json: `docs/snapshots/execution_agent_snapshot_20260715_v2.json`
- provider: `deepseek`
- scale: 24 agent tasks (easy/medium/hard)
- mcp: `REACT_AGENT_DISABLE_MCP=1`
- **report_id:** `execution_agent_snapshot_20260715_v2`
- **timestamp:** `2026-07-15T08:35:45.338235+00:00`
- **dataset:** `execution_dataset.json`
- **modes:** `agent`
- **通过率:** **24/24（100.0%）**

## 按 mode

| mode | passed | total | rate |
|------|--------|-------|------|
| `agent` | 24 | 24 | 100.0% |

## 按 difficulty

| difficulty | passed | total | rate |
|------------|--------|-------|------|
| `easy` | 8 | 8 | 100.0% |
| `hard` | 8 | 8 | 100.0% |
| `medium` | 8 | 8 | 100.0% |

## 按 tag

| tag | passed | total | rate |
|-----|--------|-------|------|
| `agent` | 24 | 24 | 100.0% |
| `calculator` | 9 | 9 | 100.0% |
| `execute_python` | 10 | 10 | 100.0% |
| `execution` | 24 | 24 | 100.0% |
| `get_time` | 1 | 1 | 100.0% |
| `grounding` | 1 | 1 | 100.0% |
| `mixed` | 2 | 2 | 100.0% |
| `multi_step` | 4 | 4 | 100.0% |
| `reasoning` | 1 | 1 | 100.0% |
| `tool_selection` | 2 | 2 | 100.0% |

## 用例明细

- **PASS** `agent_calc_17x19` [agent/easy] — Agent: compute 17*19 with calculator (22.79s) — agent outcome ok
- **PASS** `agent_calc_100_minus_37` [agent/easy] — Agent: compute 100-37 (25.5s) — agent outcome ok
- **PASS** `agent_get_time` [agent/easy] — Agent: get current time via tool (27.07s) — agent outcome ok
- **PASS** `agent_py_sum_1_to_5` [agent/easy] — Agent: execute_python sum 1..5 (31.87s) — agent outcome ok
- **PASS** `agent_calc_8x7` [agent/easy] — Agent: 8*7 via calculator (24.1s) — agent outcome ok
- **PASS** `agent_py_factorial_5` [agent/easy] — Agent: factorial 5 via python (22.47s) — agent outcome ok
- **PASS** `agent_calc_15x16` [agent/easy] — Agent: 15*16 (23.56s) — agent outcome ok
- **PASS** `agent_py_pow2_8` [agent/easy] — Agent: 2**8 via python (34.41s) — agent outcome ok
- **PASS** `agent_chain_12sq_plus7` [agent/medium] — Agent: 12*12 then +7 (25.27s) — agent outcome ok
- **PASS** `agent_paren_calc` [agent/medium] — Agent: (23+45)*2 (25.36s) — agent outcome ok
- **PASS** `agent_time_then_calc` [agent/medium] — Agent: time then 100/4 (26.5s) — agent outcome ok
- **PASS** `agent_no_search_calc` [agent/medium] — Agent: forbid search, use calculator (24.66s) — agent outcome ok
- **PASS** `agent_py_sum_evens` [agent/medium] — Agent: sum even 1..10 (35.66s) — agent outcome ok
- **PASS** `agent_ages_with_calc` [agent/medium] — Agent: age puzzle with calculator (25.75s) — agent outcome ok
- **PASS** `agent_nested_div` [agent/medium] — Agent: (100-28)/8 (22.91s) — agent outcome ok
- **PASS** `agent_py_reverse_str` [agent/medium] — Agent: reverse string via python (25.22s) — agent outcome ok
- **PASS** `agent_large_mul` [agent/hard] — Agent: 1234*5678 grounded (37.35s) — agent outcome ok
- **PASS** `agent_py_fib15` [agent/hard] — Agent: fib(15) via python (29.01s) — agent outcome ok
- **PASS** `agent_py_unique_sum` [agent/hard] — Agent: unique sum via python (23.04s) — agent outcome ok
- **PASS** `agent_dual_verify_143` [agent/hard] — Agent: calc then python verify 11*13 (22.3s) — agent outcome ok
- **PASS** `agent_fact7_plus3` [agent/hard] — Agent: 7! then +3 (23.41s) — agent outcome ok
- **PASS** `agent_py_gcd` [agent/hard] — Agent: gcd(48,18) (34.72s) — agent outcome ok
- **PASS** `agent_tool_choice_no_rag` [agent/hard] — Agent: tool choice calc not rag (23.68s) — agent outcome ok
- **PASS** `agent_py_median` [agent/hard] — Agent: median via python (21.64s) — agent outcome ok

## 诚实边界

- 本套为 **端到端 Agent（LLM 规划 + 工具）** 执行验收，绑定模型与日期
- 难度分层：`easy` 单工具、`medium` 多步/选型、`hard` 双工具/算法/禁工具约束
- 失败需区分模型失误 / 评分过严 / 工具环境；样本量仍属学习级
