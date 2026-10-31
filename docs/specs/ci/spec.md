# CI 执行子系统 Spec

## 1. 文档状态

**状态：** Active
**版本：** v1.5
**最后更新：** 2026-10-30
**负责人：** 仓库维护者

本文档定义 CI 如何为 [AI 审核与变更保障 Spec](../ai-review/spec.md) 提供确定性执行结果。CI 是被总流程调用的执行子系统，不定义整个提交流程、AI findings、人工审批或发布观察。

## 2. 目标与边界

CI 对当前 PR `head_sha` 给出可重复、可追溯、fail-closed 的机器结论：

- `pass`：所有适用 CI 门禁通过，且 required checks 与当前 head SHA 匹配；
- `fail`：代码、配置、测试、PR readiness、stage gate 或安全确定性检查失败；
- `blocked`：输入缺失、状态不完整、映射不明确或检查无法可靠判断。`blocked` 不得被 Branch Protection 当作通过。

CI 负责：

- 当前 PR 的代码、配置、工作流和 Spec/进度变更；
- changed files 到规则和门禁入口的选择；
- lint、受影响单测和最小回归；
- `scripts/ci/check_pr_ready.py` 的 PR readiness 审计；
- 代码或配置变更触发的方向 stage gate；
- required checks 的聚合、当前 head SHA 绑定和安全确定性检查。

CI 不负责：

- AI findings、风险等级、人工审批或发布/回滚编排；
- Evaluation Harness 的 Fixture、题集、Runner、评分、Replay、Episode、Trajectory 或 artifact 语义；
- 业务方向的验收内容、业务进度或生产 SLA；
- 日跑、完整评测矩阵、真实 LLM 质量结论和长期趋势。

CI 可以调用 Harness 或方向 Spec 暴露的 gate 命令，但只消费退出码和结构化摘要，不复制其测试场景、评分逻辑或阶段进度。风险和审批由 AI Review 总流程聚合。

## 3. 输入、选择与输出

每次 CI gate 必须绑定：

1. `base_sha`、`head_sha` 和 PR 编号（若来自 PR 事件）；
2. changed files 及事件类型；
3. Registry 中匹配的 rule ID、适用性和 gate 入口；
4. workflow/job 结论、退出码和可读取的 artifact。

Registry 只记录 `path_globs -> rule_id -> gate entrypoint` 及执行约束。方向 Spec 自己拥有 stage gate 命令和 evidence 结构，CI 只判断是否触发并聚合结果。

当路径没有安全映射时，CI 必须运行固定的 unmapped-safety 子集并将总状态置为 `blocked`，直到补充映射或有带原因、审批角色和到期日的一次性例外。不得静默放行，也不得在普通 PR 中无界回退到全量评测。

## 3.1 基线与阶段证据生命周期

CI 证据分为三类，不能互相替代：

- **冻结快照**：记录特定目标 SHA、采集时间、样本规则与边界、来源、采集器版本及内容校验值。快照以唯一 ID 存放，创建后不可覆盖；需要新基线时创建新 ID 并保留旧快照。
- **当前观测**：可按维护需要刷新，用于描述采集时的 main、Branch Protection 和近期运行情况。它不是历史快照，也不能单独证明阶段完成。
- **阶段复审/完成报告**：引用固定快照 ID 和 Spec revision，记录结论、未决项、命令和 artifact 校验值。重新复审须创建新报告，不覆盖旧报告。

新 main commit 不会使冻结快照或已完成的历史复审失效。当前 PR 的 readiness 和 required checks 仍必须绑定并验证当前 PR `head_sha`。阶段 gate 校验其引用快照的身份、完整性和复审状态，不要求快照 SHA 等于 gate 运行时 `HEAD`。

刷新当前观测不得修改冻结快照、历史失败日志、selector 固定样本或已发布阶段报告。快照 ID 冲突时必须失败，不得覆盖。`docs_troubleshoot` corpus baseline 是独立的文档评测数据；文档修改可按 docs 规则触发语料评估或刷新，但不因此重采 CI 历史基线或重开 Phase 0。

## 4. CI 门禁

### R1：PR readiness

每个 PR 都运行 `check_pr_ready.py`。它检查基线、提交格式、敏感配置路径、文档语料基线和仓库规定的 PR 阻断项。文档变更还必须运行 git-docs evaluation；baseline 不干净时 readiness 失败。

### R2：变更相关检查

CI 根据 Registry 和 changed files 选择最小安全检查集：格式、语法和 lint；受影响单测、导入、Schema 或最小离线回归；配置、工作流或安全边界变更的专项检查；以及适用的 Docker 或跨仓契约 smoke。映射明确时只运行相关 subset，映射不明确时使用 unmapped-safety 并保持 `blocked`。

### R3：阶段 gate

只有代码、配置或 `progress.yaml` 的阶段完成声明发生变更时，CI 才调用对应方向的 stage gate。阶段 gate 的命令、输入、状态字段和 evidence 由方向 Spec 与唯一 progress source 定义；CI 不重新解释阶段内容，也不把 Harness 阶段完成写成 CI 统一进度。

阶段 gate 缺失、取消、超时、退出非零、当前 PR head SHA 不匹配或 evidence 不可读取时，CI 结果为 `fail` 或 `blocked`。历史快照 SHA 与 gate 运行时 HEAD 不同不构成失败。普通文档编辑没有阶段状态变化时，不触发阶段 gate，只执行适用的文档和语料检查。

### R4：required checks 聚合

迁移目标是创建两个稳定 job：`CI / PR readiness` 和 `CI / PR gate`。前者输出 readiness 和选择结果；后者聚合 readiness、R2、R3、安全检查和映射状态，是唯一的合并硬门禁。条件 job、完整矩阵、日跑和阶段报告不直接加入 Branch Protection。

聚合器必须把 failure、cancelled、timed_out、action_required、缺失输入、状态缺失和 head SHA 不匹配解释为 `fail` 或 `blocked`，不能解释为通过。

### R5：安全与权限

普通 PR 使用最小 job 权限；fork PR 不读取 Secret，不执行 `pull_request_target` checkout 的不可信代码。执行不可信代码的 job 不得写仓库或修改 Branch Protection。Actions、镜像和外部依赖按仓库安全规则固定版本。安全确定性检查失败直接阻断 CI。

## 5. 本地、PR 与外部证据

| 检查层 | 目的 | 结论 |
|---|---|---|
| 本地提交前 | 快速 lint、受影响单测、配置/Schema 校验 | 提交前反馈，不替代 CI |
| PR CI | 当前 diff 的 readiness、subset、stage gate 和 required checks | 提供给 AI Review 合并编排 |
| 日跑/发布/评测 | 完整矩阵、长时方差、真实 LLM、跨环境或 Harness 质量 | evidence-only artifact，除非另有发布 gate |

外部 evidence 必须保留运行身份、版本、输入和 artifact provenance；历史、fixture/mock、held-out 和生产结果不得混为当前 PR 的 CI `pass`。

## 6. 最小验收标准

- 变更路径明确时，PR 只运行对应 subset 和必要门禁；
- 映射缺失、阶段 gate 失败或 required 输入缺失时，CI fail closed；
- `check_pr_ready.py`、lint、受影响单测和适用 stage gate 都能在当前 head SHA 上复核；
- required check 名称稳定且最终只有 `CI / PR gate` 作为合并聚合器；
- CI 文档不定义 AI findings、审批或发布流程；
- CI 文档不重复定义 Harness 的评分、Fixture、Replay 或 Episode 语义；
- docs 变更遵守 git-docs evaluation 和 baseline 规则。

## 7. CI 迁移阶段验收

CI 迁移阶段使用 `docs/specs/ci/progress.yaml` 中的唯一验收源。每项验收绑定 `acceptance_revision`；Spec 或验收语义改变时，旧验收只作为历史记录保留，并在进度源中记录 superseded 原因及替代项，不得沿用旧 gate 的通过结论。

### Phase 0：证据生命周期与当前 CI 风险基线

- 冻结快照、当前观测和阶段复审报告已分层，当前 Phase 0 快照具唯一 ID、目标 SHA、采集时间、采样边界、来源和可校验内容清单。
- 快照不可覆盖；更新当前观测不会改动历史快照、失败日志或阶段报告。
- gate 验证引用快照的身份、完整性和复审状态，不比较快照 SHA 与运行时 HEAD。
- 文档 corpus baseline 与 CI 历史样本生命周期明确分离。
- 新 Spec revision 下的独立复审已完成。没有新复审时 Phase 0 保持 `partial`。

### Phase 1：Registry 与固定样本选择器

- Registry v2 语义验证通过，负例覆盖重复规则、无效路径、过期例外及不安全 gate 配置。
- Selector backtest 只消费带固定 ID 和来源 SHA 的样本输入；不得把每次查询最新 PR 的结果称为冻结回放。
- 报告 mapped/unmapped 结果。缺少独立标注的误选/漏选指标必须保持未测量，不得推断通过。
- R9 的 fork Secret 隔离及有效运行权限须有隔离远端执行证据；本地静态快照不能替代该证据。
- Phase 1 只有所有新验收项通过后才能标记完成。

## 8. 相关入口

- [AI 审核与变更保障 Spec](../ai-review/spec.md)
- [CI 子系统迁移计划](redesign-plan.md)
- [Harness 构建与统一契约 Spec](../harness/spec.md)
- [Spec 注册表](../registry.yaml)
- [PR 就绪审计](../../../scripts/ci/check_pr_ready.py)
- [测试工作流](../../../.github/workflows/test.yml)
