# 提案：明确 CI 基线与阶段证据生命周期

**状态：** Accepted；已并入 CI Spec v1.5
**范围：** CI Phase 0 基线、滚动观测及阶段验收证据
**目的：** 消除“基线冻结”与反复刷新同一组文件之间的语义冲突。

## 问题

CI 迁移计划将 Phase 0 定义为基线冻结，但 `refresh_phase0_baseline.py` 每次采集都会覆盖固定路径下的 JSON、Markdown、样本索引和 R9 快照。采集范围又是最新 PR 与 workflow runs 的滑动窗口，因此这些文件实际表示最新观测，而非不可变的冻结基线。

当前阶段门禁还要求基线记录的默认分支 SHA 等于运行时 `HEAD`。如果更新后的基线随 PR 合入主干，提交本身就会改变 main SHA；继续要求相等会使基线在提交后立即显得过期，诱发再次采集。历史快照、当前观测和当前 PR 的检查身份因此被混为一谈。

## 提议的证据模型

1. **冻结快照**：一次性记录特定目标 SHA、采集时间、采样规则、样本边界、采集器版本和来源。快照创建后不可覆盖；需要新基线时创建新的快照 ID，并保留旧快照。
2. **当前观测**：可按维护需要重新采集，表示采集时观察到的 main、Branch Protection 和近期运行情况。它不是历史快照，也不能单独证明 Phase 0 完成。
3. **阶段复审/完成报告**：引用一个明确的冻结快照 ID，并记录复审结论、未决项及报告身份。main 前进不改变该历史结论；若重新评审，应新增报告并明确引用新的快照。

当前 PR 的 CI/readiness 仍绑定该 PR 的 `head_sha`，并对适用检查重新验证。历史快照 SHA 描述采集对象，不充当当前 PR 的 required-check 身份，也不要求等于之后每个 main SHA。

`docs_troubleshoot` 的 corpus baseline 是独立的评测语料基线。按仓库 docs 规则，它可能因文档内容变化而需要评估或刷新，但不因此要求重新采集 GitHub 历史样本或重开 CI Phase 0。

## 生命周期约束

- 新快照必须有稳定且唯一的 ID；ID 至少能区分采集目标和采集批次，快照内容同时记录完整目标 SHA 与采集时间。
- 创建快照时不得覆盖已存在的快照目录或文件；冲突时失败并要求选择新 ID。
- 刷新当前观测不得修改冻结快照、历史失败日志或已发布的阶段报告。
- 阶段进度只引用被复审的快照 ID；只有维护者明确启动新的 Phase 0 基线周期时，才创建新快照。
- 新 main commit 使当前 PR/commit 的检查按现行规则重新运行，但不会令已有历史证据失效。
- 阶段 gate 应验证被引用快照的存在性、完整性和复审状态，不要求快照 SHA 等于 gate 运行时 `HEAD`。
- 现有资料迁移时保留原文件和历史来源；明确标记旧记录的身份与用途，不静默改写历史含义。

## 已有构建盘点

| 判定 | 路径/构建 | 提案获批后的处理方向 |
|---|---|---|
| 符合目标，可保留 | `docs/specs/ci/evidence/archive/2026-10-22/`、`archive/2026-10-29-e641adc7/`、历史失败日志 | 作为只读历史证据保留，不因 main 前进而重采或覆盖。 |
| 符合目标，可保留 | `docs/specs/ci/registry-v2.schema.json`、`registry-v2.json`、`scripts/ci/registry_v2.py`、`tests/test_ci_registry_v2.py` | 属于 Registry/选择器基础设施，与基线生命周期中性；提案获批前暂停扩展其阶段验收。 |
| 调整后保留 | 当前 `phase0-baseline.*`、样本索引与 R9 快照 | 保留现有采集结果；明确它们对应的采集批次，不再把可覆盖固定路径当作不可变快照身份。 |
| 调整后保留 | `scripts/ci/refresh_phase0_baseline.py` | 保留采集能力；后续明确区分创建不可变快照与刷新当前观测，禁止静默覆盖快照。 |
| 调整后保留 | `scripts/ci/selector_backtest.py`、Phase 1 selector backtest evidence | 当前脚本会重新查询 GitHub PR；后续改为消费固定样本输入，或明确输出为滚动观测，避免把变化中的窗口称为冻结回放。 |
| 调整后保留 | `docs/specs/ci/progress.yaml`、CI registry 注册及 `scripts/ci/ci_stage_gate.py` | 保留单一进度源和 gate 方向；阶段报告改为引用固定 snapshot ID，不能要求历史 SHA 等于最新 HEAD。 |
| 仅冲突部分应回退 | `ci_stage_gate.py` 中 `baseline SHA == HEAD SHA` 条件 | 移除历史快照与运行时 HEAD 的等值要求；后续 gate 检查快照身份、完整性和复审状态。 |
| 仅冲突部分应回退 | 刷新器对 `phase0-baseline.*`、样本索引和 R9 固定文件的原位覆盖行为 | 移除覆盖冻结快照的行为；保留采集器和原始证据，不删除归档。 |

`refresh_docs_baseline.py` 与 `check_pr_ready.py` 管理文档评测语料，应继续独立于 CI Phase 0 生命周期。其他工作区中的 AI Review、Harness、根进度、审查目录及临时材料不属于本提案的回退对象。

## 变更与批准边界

本提案已被批准为 CI Spec v1.5 的生命周期约束。依赖旧的“baseline SHA 必须等于当前 HEAD”语义的验收、gate 报告或批准记录必须标记为 `superseded`，保留原报告及其证据，不再作为当前 Phase 0/1 的通过依据。实现验收至少应证明：快照创建不可覆盖、main 前进不会使历史快照失效、当前 PR 检查仍绑定 PR head SHA、selector backtest 可重放固定样本。

由于本提案位于 `docs/`，按仓库文档规则评估受影响的 Git Docs 断言；只有断言仍成立时，才在同一文档变更中刷新 corpus baseline。
