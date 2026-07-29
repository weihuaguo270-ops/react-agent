# StepWatcher 跨仓证据报告

- **report_id:** `step_watcher_evidence_20260729_054105`
- **timestamp:** `2026-07-29T05:41:05.498638+00:00`
- **scenarios:** 6 (pass 6)
- **pass_rate:** 100%
- **golden suite (trace-debugger):** 1.0
- **git:** `51bea35`

## 场景结果

| id | expected | detected | jsonl | pass |
|----|----------|----------|------:|------|
| `live_tool_error` | tool_error | tool_error | 1 | PASS |
| `live_search_empty_then_ok` | search_empty | search_empty | 1 | PASS |
| `live_duplicate_blocked` | duplicate,search_empty | duplicate,search_empty | 2 | PASS |
| `live_pass_clean` | - | - | 0 | PASS |
| `live_no_answer` | no_answer | no_answer | 1 | PASS |
| `live_offtrack` | llm_offtrack | llm_offtrack | 1 | PASS |

## 复现

```bash
pip install -e ../trace-debugger
python examples/eval/run_step_watcher_evidence.py --publish
python -m pytest tests/test_step_watcher_golden_e2e.py -v
```

## 诚实边界

- 场景为 Harness 录制模拟，非 live LLM
- failure_tags 为启发式；与 golden 集分栏引用
