# CI 当前观测报告

## 状态

**证据类型：** `current_observation`<br>
**验收边界：** 采样与静态安全证据不构成阶段通过；阶段状态仅见 `../progress.yaml`。<br>
**采集时间：** 2026-11-03T03:26:03.197942+00:00<br>
**仓库：** weihuaguo270-ops/react-agent
**默认分支 SHA：** `16d03460fab16914a2752698aeb0053e32f5a3a0`<br>
**来源：** GitHub Actions、Pull Request、Branch Protection 只读 API 快照。

本报告只记录采集时的事实，不把 Registry v2、路径映射、聚合器或 Branch Protection 迁移解释为已完成。当前观测可刷新；冻结快照和历史失败证据不可覆盖。

## 样本与方法

- PR 样本：100 条，范围 `2026-09-27T06:23:01Z` 至 `2026-11-02T10:00:16Z`。
- `test.yml`：100 次，结论统计 `{"success": 64, "failure": 34, "cancelled": 2}`。
- `daily-smoke.yml`：50 次，结论统计 `{"success": 43, "failure": 7}`。
- 每个失败、取消、超时或 action-required run 都通过 Jobs API 展开到失败 job/step；分类仅作定位提示，不能替代日志根因。

## Workflow 职责映射

| Workflow | Job | 逻辑测试组 | 运行模式 | 目标阶段 | 当前 required |
|---|---|---|---|---|---:|
| `test.yml` | `PR ready audit` | `pr_readiness` | `pull_request_only` | `Phase 2` | no |
| `test.yml` | `lint` | `lint` | `offline` | `Phase 2-3` | yes |
| `test.yml` | `test` | `python_matrix_and_offline_tests` | `offline_plus_sibling_repositories` | `Phase 2` | yes |
| `test.yml` | `test-windows` | `windows_matrix_and_console_guards` | `offline` | `Phase 2` | yes |
| `test.yml` | `typecheck` | `typecheck` | `static` | `Phase 2-3` | yes |
| `test.yml` | `security` | `dependency_security` | `offline_dependency_audit` | `Phase 2-3` | yes |
| `test.yml` | `docker-smoke` | `docker_runtime_smoke` | `docker` | `Phase 2-3` | yes |
| `daily-smoke.yml` | `daily-smoke` | `daily_smoke_evidence` | `offline_mock_evidence_only` | `Phase 0` | no |
| `harness.yml` | `Harness P4 stage gate` | `stage_gate` | `harness_stage_gate` | `direction_spec` | yes |
| `evaluation.yml` | `Evaluation evidence` | `evaluation_evidence` | `evidence_only` | `Phase 0` | no |

该表仅记录逻辑组职责，required 状态来自本次 Branch Protection 采集；它不替代 Registry 或 Phase 1 selector backtest。

## 当前 Required Checks

- `lint`
- `test (3.10)`
- `test (3.11)`
- `test-windows (3.10)`
- `test-windows (3.11)`
- `typecheck`
- `security`
- `docker-smoke`
- `Harness P4 stage gate`

Branch Protection：strict=True，管理员保护=True，线性历史=True，稳定聚合器=False。

聚合器是否 required 以本次保护规则为准。Evaluation、真实 LLM 及 Harness 质量证据不由本报告推断；Secret 探测不等价于 live smoke 通过。

## PR #172/#173 合并提交关联 runs（按实际事件保留）

- PR #173：run `40166797286`，workflow `daily-smoke.yml`，event `schedule`，conclusion `success`，head `8446201e6495c7a302a80347bcaa0c8e7bf613fd`
- PR #173：run `40104979077`，workflow `evaluation.yml`，event `push`，conclusion `success`，head `8446201e6495c7a302a80347bcaa0c8e7bf613fd`
- PR #173：run `40104979076`，workflow `harness.yml`，event `push`，conclusion `success`，head `8446201e6495c7a302a80347bcaa0c8e7bf613fd`
- PR #173：run `40104979097`，workflow `test.yml`，event `push`，conclusion `success`，head `8446201e6495c7a302a80347bcaa0c8e7bf613fd`
- PR #172：run `40102484146`，workflow `test.yml`，event `workflow_dispatch`，conclusion `success`，head `e9187069684797ef5dd6cab830cafd3332880a06`
- PR #172：run `40101788736`，workflow `test.yml`，event `workflow_dispatch`，conclusion `success`，head `e9187069684797ef5dd6cab830cafd3332880a06`
- PR #172：run `40101578011`，workflow `harness.yml`，event `push`，conclusion `success`，head `e9187069684797ef5dd6cab830cafd3332880a06`
- PR #172：run `40101578014`，workflow `evaluation.yml`，event `push`，conclusion `success`，head `e9187069684797ef5dd6cab830cafd3332880a06`

## 时长快照

| Workflow | N | P50 | P95 | 最大 |
|---|---:|---:|---:|---:|
| `test.yml` | 100 | 3.21 | 4.97 | 1371.82 |
| `daily-smoke.yml` | 50 | 2.91 | 5.53 | 9.17 |

这些是从创建到更新时间的墙钟近似值，包含排队，不能直接作为 PR gate 执行时长目标。

## Phase 0 退出结论

Phase 0 由冻结快照完整性、证据生命周期分离、gate 校验和当前 Spec 下的独立复审决定。当前观测不能替代独立复审，也不要求 Phase 1 语义校验、R9 远端执行或 Phase 2 shadow 窗口先完成。本采集器不执行 selector，因此 mapping coverage 保持 `not_measured`；已执行的 Phase 1 结果见唯一进度源。

## 复核边界

- 复现命令：见 JSON 的 `reproduction`。
- 限制：见 JSON 的 `limitations`。
- R9 静态安全快照：见 `phase0-r9-security-snapshot.md`；其中的 finding 是待整改项，不是通过结论。
