# Execution Agent 扩容快照（execution_agent_snapshot_20260716_v3）

- git: `98817ff`
- archived_json: `docs/snapshots/execution_agent_snapshot_20260716_v3.json`
- scale: 36 agent tasks (easy/medium/hard expanded)
- mcp: `REACT_AGENT_DISABLE_MCP=1`
- **report_id:** `execution_agent_snapshot_20260716_v3`
- **timestamp:** `2026-07-16T01:33:25.939548+00:00`
- **dataset:** `execution_dataset.json`
- **modes:** `agent`
- **通过率:** **36/36（100.0%）**

## 按 mode

| mode | passed | total | rate |
|------|--------|-------|------|
| `agent` | 36 | 36 | 100.0% |

## 按 difficulty

| difficulty | passed | total | rate |
|------------|--------|-------|------|
| `easy` | 8 | 8 | 100.0% |
| `hard` | 16 | 16 | 100.0% |
| `medium` | 12 | 12 | 100.0% |

## 按 tag

| tag | passed | total | rate |
|-----|--------|-------|------|
| `agent` | 36 | 36 | 100.0% |
| `calculator` | 12 | 12 | 100.0% |
| `execute_python` | 16 | 16 | 100.0% |
| `execution` | 36 | 36 | 100.0% |
| `get_time` | 1 | 1 | 100.0% |
| `grounding` | 2 | 2 | 100.0% |
| `mixed` | 3 | 3 | 100.0% |
| `multi_step` | 7 | 7 | 100.0% |
| `reasoning` | 1 | 1 | 100.0% |
| `tool_selection` | 4 | 4 | 100.0% |

## 用例明细

- **PASS** `agent_calc_17x19` [agent/easy] — Agent: compute 17*19 with calculator (15.98s) — agent outcome ok
- **PASS** `agent_calc_100_minus_37` [agent/easy] — Agent: compute 100-37 (18.5s) — agent outcome ok
- **PASS** `agent_get_time` [agent/easy] — Agent: get current time via tool (18.95s) — agent outcome ok
- **PASS** `agent_py_sum_1_to_5` [agent/easy] — Agent: execute_python sum 1..5 (31.13s) — agent outcome ok
- **PASS** `agent_calc_8x7` [agent/easy] — Agent: 8*7 via calculator (18.22s) — agent outcome ok
- **PASS** `agent_py_factorial_5` [agent/easy] — Agent: factorial 5 via python (20.16s) — agent outcome ok
- **PASS** `agent_calc_15x16` [agent/easy] — Agent: 15*16 (19.9s) — agent outcome ok
- **PASS** `agent_py_pow2_8` [agent/easy] — Agent: 2**8 via python (19.62s) — agent outcome ok
- **PASS** `agent_chain_12sq_plus7` [agent/medium] — Agent: 12*12 then +7 (32.58s) — agent outcome ok
- **PASS** `agent_paren_calc` [agent/medium] — Agent: (23+45)*2 (20.73s) — agent outcome ok
- **PASS** `agent_time_then_calc` [agent/medium] — Agent: time then 100/4 (25.09s) — agent outcome ok
- **PASS** `agent_no_search_calc` [agent/medium] — Agent: forbid search, use calculator (19.39s) — agent outcome ok
- **PASS** `agent_py_sum_evens` [agent/medium] — Agent: sum even 1..10 (21.64s) — agent outcome ok
- **PASS** `agent_ages_with_calc` [agent/medium] — Agent: age puzzle with calculator (20.95s) — agent outcome ok
- **PASS** `agent_nested_div` [agent/medium] — Agent: (100-28)/8 (17.61s) — agent outcome ok
- **PASS** `agent_py_reverse_str` [agent/medium] — Agent: reverse string via python (18.18s) — agent outcome ok
- **PASS** `agent_large_mul` [agent/hard] — Agent: 1234*5678 grounded (18.51s) — agent outcome ok
- **PASS** `agent_py_fib15` [agent/hard] — Agent: fib(15) via python (17.1s) — agent outcome ok
- **PASS** `agent_py_unique_sum` [agent/hard] — Agent: unique sum via python (23.59s) — agent outcome ok
- **PASS** `agent_dual_verify_143` [agent/hard] — Agent: calc then python verify 11*13 (20.04s) — agent outcome ok
- **PASS** `agent_fact7_plus3` [agent/hard] — Agent: 7! then +3 (18.5s) — agent outcome ok
- **PASS** `agent_py_gcd` [agent/hard] — Agent: gcd(48,18) (18.33s) — agent outcome ok
- **PASS** `agent_tool_choice_no_rag` [agent/hard] — Agent: tool choice calc not rag (17.55s) — agent outcome ok
- **PASS** `agent_py_median` [agent/hard] — Agent: median via python (17.72s) — agent outcome ok
- **PASS** `agent_med_calc_19x21` [agent/medium] — Agent: 19*21 (16.99s) — agent outcome ok
- **PASS** `agent_med_chain_5sq` [agent/medium] — Agent: 5*5 then *3 (26.88s) — agent outcome ok
- **PASS** `agent_med_py_odds_sum` [agent/medium] — Agent: sum odds 1..9 (21.02s) — agent outcome ok
- **PASS** `agent_med_forbid_search_99` [agent/medium] — Agent: 33*3 no search (21.38s) — agent outcome ok
- **PASS** `agent_hard_dual_12x13` [agent/hard] — Agent: dual verify 12*13 (21.36s) — agent outcome ok
- **PASS** `agent_hard_py_fib12` [agent/hard] — Agent: fib(12) (19.27s) — agent outcome ok
- **PASS** `agent_hard_py_lcm` [agent/hard] — Agent: lcm via python (26.39s) — agent outcome ok
- **PASS** `agent_hard_calc_999x999` [agent/hard] — Agent: 999*999 grounded (19.03s) — agent outcome ok
- **PASS** `agent_hard_py_sort_join` [agent/hard] — Agent: sort join digits (20.13s) — agent outcome ok
- **PASS** `agent_hard_no_rag_mul` [agent/hard] — Agent: 25*25 no rag (16.18s) — agent outcome ok
- **PASS** `agent_hard_py_primes_count` [agent/hard] — Agent: count primes <=20 (18.58s) — agent outcome ok
- **PASS** `agent_hard_chain_fact6` [agent/hard] — Agent: 6! minus 20 (18.48s) — agent outcome ok

## 诚实边界

- 本套为 **端到端 Agent（LLM 规划 + 工具）** 执行验收，绑定模型与日期
- 难度分层：`easy` 单工具、`medium` 多步/选型、`hard` 双工具/算法/禁工具约束
- 失败需区分模型失误 / 评分过严 / 工具环境；样本量仍属学习级
