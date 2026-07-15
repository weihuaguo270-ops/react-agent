# Execution 公开快照（execution_snapshot_20260715）

- git: 6f1b7c6
- archived_json: docs/snapshots/execution_snapshot_20260715.json
- reproduce: python examples/run_execution_suite.py --publish
- **report_id:** `execution_snapshot_20260715`
- **timestamp:** `2026-07-15T08:00:00+00:00`
- **dataset:** `execution_dataset.json`
- **mode:** `offline_tools`（不经 LLM，直接执行工具）
- **通过率:** **8/8（100.0%）**

## 按 tag

| tag | passed | total | rate |
|-----|--------|-------|------|
| `calculator` | 3 | 3 | 100.0% |
| `execute_python` | 3 | 3 | 100.0% |
| `execution` | 8 | 8 | 100.0% |
| `get_time` | 1 | 1 | 100.0% |
| `mixed` | 1 | 1 | 100.0% |
| `multi_step` | 2 | 2 | 100.0% |

## 用例明细

- **PASS** `exec_calc_mul` — calculator: 17*19 (0.0s) — all steps ok
- **PASS** `exec_calc_div` — calculator: 144/12 (0.0s) — all steps ok
- **PASS** `exec_calc_chain` — calculator two-step chain (0.0s) — all steps ok
- **PASS** `exec_get_time_format` — get_time returns YYYY-MM-DD HH:MM:SS (0.0s) — all steps ok
- **PASS** `exec_py_sum` — execute_python: print sum (0.058s) — all steps ok
- **PASS** `exec_py_json_roundtrip` — execute_python: json roundtrip (0.031s) — all steps ok
- **PASS** `exec_py_fib` — execute_python: fib(10) (0.029s) — all steps ok
- **PASS** `exec_mixed_calc_then_py` — mixed: calc then python verify (0.042s) — all steps ok

## 诚实边界

- 本套为 **工具执行验收**，不是端到端 Agent（LLM 规划）成功率
- 数字绑定具体 `report_id`；改工具语义后需重跑
