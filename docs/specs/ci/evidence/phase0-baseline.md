# CI Phase 0 基线报告

## 状态

**阶段状态：** Partial（基线快照和安全快照已刷新；独立复审、Registry v2 语义校验和 R9 验收仍未完成）<br>
**采集时间：** 2026-10-24T04:19:00.896700+00:00<br>
**仓库：** weihuaguo270-ops/react-agent  
**默认分支 SHA：** `b9d4334896eb15f39f99991b594b9d6bd10f523c`<br>
**来源：** GitHub Actions、Pull Request、Branch Protection 只读 API 快照。

本报告只冻结当前事实，不把 Registry v2、路径映射、聚合器或 Branch Protection 迁移解释为已完成。

## 样本与方法

- PR 样本：100 条，范围 `2026-09-13T05:44:09Z` 至 `2026-10-24T01:44:14Z`。
- `test.yml`：100 次，结论统计 `{"success": 54, "failure": 45, "cancelled": 1}`。
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
| `test.yml` | `real-llm-gate` | `real_llm_secret_probe` | `secret_probe` | `Phase 2` | yes |
| `test.yml` | `real-llm-smoke/full` | `real_llm_smoke` | `live_provider` | `Phase 2-3` | no |
| `daily-smoke.yml` | `daily-smoke` | `daily_variance_and_optional_agent_smoke` | `offline_mock_plus_optional_live_agent` | `Phase 2` | no |

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
- `Real LLM gate`

Branch Protection：strict=True，管理员保护=True，线性历史=True，稳定聚合器=False。

当前仍没有稳定聚合器；`Real LLM gate` 只表示 Secret 探测，不等价于实际 smoke 通过。

## 时长快照

| Workflow | N | P50 | P95 | 最大 |
|---|---:|---:|---:|---:|
| `test.yml` | 100 | 2.57 | 4.88 | 65.72 |
| `daily-smoke.yml` | 50 | 0.46 | 4.72 | 9.17 |

这些是从创建到更新时间的墙钟近似值，包含排队，不能直接作为 PR gate 执行时长目标。

## Phase 0 退出结论

仍待完成：独立复审逐样本证据、Phase 1 语义校验和 R9 正式验收。Phase 1 验收矩阵已冻结并复核为后续契约，但没有在本阶段执行。当前 v1 Registry 没有 path rules，因此 mapping coverage 保持 `not_measured`，不得伪造历史覆盖率。

## 复核边界

- 复现命令：见 JSON 的 `reproduction`。
- 限制：见 JSON 的 `limitations`。
- R9 静态安全快照：见 `phase0-r9-security-snapshot.md`；其中的 finding 是待整改项，不是通过结论。
