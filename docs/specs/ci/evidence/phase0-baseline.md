# CI Phase 0 基线报告

## 状态

**阶段状态：** Partial（基线快照和安全快照已刷新；独立复审、Registry v2 语义校验和 R9 验收仍未完成）<br>
**采集时间：** 2026-10-30T12:58:44.069291+00:00<br>
**仓库：** weihuaguo270-ops/react-agent
**默认分支 SHA：** `8805e5e9a875eb6584aa12d1ce79917ee7e73076`<br>
**来源：** GitHub Actions、Pull Request、Branch Protection 只读 API 快照。

本报告只冻结当前事实，不把 Registry v2、路径映射、聚合器或 Branch Protection 迁移解释为已完成。

## 样本与方法

- PR 样本：100 条，范围 `2026-09-24T05:55:34Z` 至 `2026-10-30T10:38:47Z`。
- `test.yml`：100 次，结论统计 `{"success": 60, "failure": 38, "cancelled": 2}`。
- `daily-smoke.yml`：50 次，结论统计 `{"success": 43, "failure": 7}`。
- 每个失败、取消、超时或 action-required run 都通过 Jobs API 展开到失败 job/step；分类仅作定位提示，不能替代日志根因。

## Workflow 职责映射

| Workflow | Job | 逻辑测试组 | 运行模式 | 目标阶段 | 当前 required |
|---|---|---|---|---|---:|
| `test.yml` | `pr-ready` | `pr_readiness` | `pull_request_only` | `Phase 2` | yes |
| `test.yml` | `lint` | `lint` | `offline` | `Phase 2-3` | yes |
| `test.yml` | `test` | `python_matrix_and_full_offline_evaluation` | `offline_plus_sibling_repositories` | `Phase 2` | yes |
| `test.yml` | `test-windows` | `windows_matrix_and_console_guards` | `offline` | `Phase 2` | yes |
| `test.yml` | `typecheck` | `typecheck` | `static` | `Phase 2-3` | yes |
| `test.yml` | `security` | `dependency_security` | `offline_dependency_audit` | `Phase 2-3` | yes |
| `test.yml` | `docker-smoke` | `docker_runtime_smoke` | `docker` | `Phase 2-3` | yes |
| `daily-smoke.yml` | `daily-smoke` | `daily_smoke_evidence` | `offline_mock_evidence_only` | `Phase 0` | no |
| `harness.yml` | `Harness P4 stage gate` | `stage_gate` | `harness_stage_gate` | `direction_spec` | yes |
| `evaluation.yml` | `Evaluation evidence` | `evaluation_evidence` | `evidence_only` | `Phase 0` | no |

该表是 Registry v2 之前的初步迁移表；它不表示路径映射已经实现。

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

当前仍没有稳定聚合器；`Real LLM gate` 只表示 Secret 探测，不等价于实际 smoke 通过。

## PR #172/#173 合并后 push runs

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
| `test.yml` | 100 | 3.15 | 4.97 | 1371.82 |
| `daily-smoke.yml` | 50 | 2.91 | 5.53 | 9.17 |

这些是从创建到更新时间的墙钟近似值，包含排队，不能直接作为 PR gate 执行时长目标。

## Phase 0 退出结论

仍待完成：独立复审逐样本证据、Phase 1 语义校验和 R9 正式验收。Phase 1 验收矩阵已冻结并复核为后续契约，但没有在本阶段执行。当前 v1 Registry 没有 path rules，因此 mapping coverage 保持 `not_measured`，不得伪造历史覆盖率。

## 复核边界

- 复现命令：见 JSON 的 `reproduction`。
- 限制：见 JSON 的 `limitations`。
- R9 静态安全快照：见 `phase0-r9-security-snapshot.md`；其中的 finding 是待整改项，不是通过结论。
