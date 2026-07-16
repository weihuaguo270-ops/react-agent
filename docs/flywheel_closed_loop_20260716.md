# 失败飞轮闭环对照（flywheel_closed_loop_20260716）

- **report_id:** `flywheel_closed_loop_20260716_014112`
- **timestamp:** `2026-07-16T01:41:12.345901+00:00`
- **react-agent git:** `d888012`
- **trace-debugger git:** `2f1a3dc`

## 本轮落地改动

- react-agent: block adjacent identical tool calls (REACT_AGENT_BLOCK_DUPLICATE_TOOLS=1)
- react-agent: prompt rules 6–7 (no duplicate / stay on short factual Q)
- trace-debugger: skip llm_offtrack when answer grounded in tool observations / short-fact+digits

## 单元核验

- duplicate 参数规范化: **PASS**
- 「现在几点了」不再误报 offtrack: **PASS** ([])

## 真实轨迹分布：改前 → 改后

- 改前源: `D:/agent_learning/trace-debugger/docs/snapshots/tdebug_failure_real_20260715.json` (n=100)
- 改后源: `D:/agent_learning/react-agent/src/react_agent/trajectories` (n=100)
- 改后说明: reanalyze same files from before snapshot (100 found)

| type | before | after | delta |
|------|-------:|------:|------:|
| `duplicate` | 1 | 1 | +0 |
| `llm_offtrack` | 6 | 1 | -5 |
| `no_answer` | 1 | 1 | +0 |
| `tool_error` | 2 | 2 | +0 |

## 解读

- **公平对照**：改后优先按改前快照中的同一批文件名重扫（只换分析器），避免混入 flaky/新评测轨迹
- **llm_offtrack 下降**：多为短问答假阳性修复（答案 grounded 于工具观测），不是模型突然变聪明
- **duplicate**：Harness 层已拦截相邻同参；历史轨迹不会被改写，需新跑任务才能在新 traj 上体现
- 闭环清单见 [FAILURE_FLYWHEEL.md](./FAILURE_FLYWHEEL.md)

## 复现

```bash
python examples/run_flywheel_closed_loop.py --publish
```
