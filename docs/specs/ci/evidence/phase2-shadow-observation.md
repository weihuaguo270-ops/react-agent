# CI Phase 2 Shadow Observation

**状态：** `Blocked`（report-only 聚合器已实现，观察窗口尚未开始）

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

当前尚未有可计入窗口的 live aggregate report。Phase 1 的 R9 外部 fork
隔离运行仍缺证据，因此本阶段只能保持 report-only。
