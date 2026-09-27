# 失败回归：三句话 + 一张图

面向 Agent 应用研发 / 评测 / AI 质量工程的答辩口径。  
**不说**自动优化 Agent；**只说**可复现的检出、门禁与复验。

## 三句话

1. **失败自动检出**：react-agent 跑任务并产出 Format B 轨迹与 EvaluationEpisode；trace-debugger 扫描失败类型与分布回归。  
2. **回归门禁**：llm-eval-engine 用业务终态 + process quality + failure-gate 做 `pass / review / hold`；sibling 缺失 fail-closed。  
3. **修复后强制复验**：hold 信号进入 `repair_feedback` 驱动 RepairLoop/人工修复；必须对冻结 baseline 复跑且 `improved_to_pass` 才放行。

## 一张图

```text
react-agent（任务 / Episode / Format B）
        │
        ├─► trace-debugger（scan / compare / findings / failure-gate）
        │
        └─► llm-eval-engine（process quality + evidence bundle → pass|review|hold）
                    │
         hold/review ──► repair_feedback → RepairLoop / 人工修复
                    │
         强制复验（reverify_from + 冻结 baseline_scan）
                    │
              improved_to_pass 才允许成功放行
```

## 可写 / 不可写

| 可写 | 不可写 |
|------|--------|
| **对齐工作流已在夹具 + 3 条 SoftwareTask 上复现** | 生产 SLA、降本、上游合并率 |
| 失败自动检出 → 回归门禁 → 修复后强制复验（`improved_to_pass`） | Agent 自优化 / 自进化 |
| 冻结 baseline 下坏补丁 hold、好补丁 pass（跨 run，非自比） | 已上线可靠服务 |

## 证据入口（简历可链）

| 项 | 路径 |
|----|------|
| 编排说明 | [`FAILURE_REGRESSION_PIPELINE.md`](./FAILURE_REGRESSION_PIPELINE.md) |
| 共享门禁 | `src/react_agent/eval/failure_regression_gate.py` |
| 夹具流水线 | `examples/eval/run_failure_regression_pipeline.py` + `examples/fixtures/failure_regression/` |
| SoftwareTask 验收 | `examples/eval/run_software_task_failure_regression.py` |
| 紧凑 Agent 信封（CI） | `examples/fixtures/software_tasks/fastapi-{15764,15974,16253}-agent.json` |
| 真实产物（本地绿跑后） | `artifacts/failure-regression/software-tasks/acceptance_summary.json` |
| 三任务独立门禁 | `artifacts/failure-regression/software-tasks/good|bad/fastapi-*/{release,findings,process_quality}.json` |
| 冻结 baseline | `artifacts/failure-regression/software-tasks/frozen_baseline_scan.json` |
| 复验剧本 | `artifacts/failure-regression/software-tasks/reverify/{parent-hold,child-pass}/` |
| 带门禁的 Agent run | `artifacts/software-tasks/runs/fastapi-*-agent-gated.json` |
| CI | `.github/workflows/test.yml`（夹具 P0 + SoftwareTask 验收 + 契约测） |
| 契约 / 验收测 | `tests/test_failure_regression_contracts.py` · `tests/test_software_task_failure_regression.py` |

## 明确不证明

- 不证明 Agent 会自进化或自动改好自己  
- 不证明生产 SLA、降本或上游合并率  
- Shadow / 离线证据 ≠ 已上线可靠服务
