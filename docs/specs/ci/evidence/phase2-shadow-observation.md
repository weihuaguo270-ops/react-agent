# CI Phase 2 Shadow Observation

**状态：** `Blocked`（report-only 聚合器已实现，当前 live observation 只有 3 天）

当前最新观测证据来自 PR #207 的 Phase 2 分支 `d891673628fdfe064627acbdfcb3bfe3103d0389` 上的
shadow workflow run [42510977744](https://github.com/weihuaguo270-ops/react-agent/actions/runs/42510977744)，
结构化报告见 [`phase2-shadow-observation-2026-11-09-run-42510977744.json`](phase2-shadow-observation-2026-11-09-run-42510977744.json)。
本次 run 成功生成 24 个有效样本和 24 个不同的 `head_sha`，其中 5 个有完整
runtime 对比（中位改善暂未计算，尚不足 10 个）。PR #207 的 `d891673` 样本选择完整检查集，不属于严格缩小样本。报告记录了
`repository`、`run_id`、`run_url` 和 `collector_head_sha` provenance；没有 invalid sample、
unmapped path 或 expected-check 漏选，并包含 PR #206、#207 的 report-only artifact。运行
42509905741 及更早运行的结构化报告和原始 workflow artifacts 均保留；完整 excluded run ID 与原因仍以对应 workflow artifact 为准。

本报告只记录 Phase 2 的当前边界，不把历史 backtest 或单次 PR artifact
解释为观察窗口通过。`.github/workflows/test.yml` 现在为每个 PR 同时上传：

- `pr-check-scope.json`：Registry selector 的选择结果；
- `expected-pr-checks.json`：独立 expected-check policy 的结果。

`scripts/ci/aggregate_shadow_observation.py` 只接受两个 artifact 在相同
`pr_number`、`base_sha`、`head_sha` 和 changed paths 上配对。它会保留缺失
artifact、SHA 不匹配、漏选和不可比较的 runtime 样本；同一 `head_sha` 的
重跑只记录为 excluded，不重复计数，也不会阻断窗口，并在以下
条件全部满足前输出 `blocked`：14 个连续日历日、10 个不同 head SHA、3 类
确实缩小的规则、零 expected-check 漏选、10 个可比较 runtime SHA，以及至少
20% 的 runtime 改善中位数。该报告不会修改 required checks 或 Branch
Protection。

`.github/workflows/shadow-observation.yml` 每日以只读权限收集最近的
`test.yml` PR runs，下载并绑定两个 report-only artifact，再从同一 workflow
attempt 的 job 时间戳生成明确标注的 runtime estimate。下载失败、过期 artifact、
缺少 job 或失败 job 都会保留在 `excluded_runs`/`invalid_samples` 中，不能被
静默删除或当作有效样本。

本次 live aggregate report 的 `conclusion` 仍为 `blocked`：观察窗口只有 3 天，
已有 24 个不同 `head_sha`，但只有 `docs` 与 `docs+docs_corpus_baseline` 两个严格缩小
规则类别，可比 runtime 为 5，尚未满足 14 天、3 类缩小规则、10 个 runtime 样本及至少
20% 中位改善的全部门槛。Phase 1
的 R9 外部 fork 隔离运行也仍缺当前 head 的有效证据，因此本阶段继续保持 report-only，
不授权 subset gate 或 Branch Protection 变更。
