# CI 执行子系统 Spec

## 1. 文档状态

**状态：** Proposed
**版本：** v1.4
**最后更新：** 2026-10-29
**负责人：** 仓库维护者

本文档定义 CI 如何为 [AI 审核与变更保障 Spec](../ai-review/spec.md) 提供确定性执行结果。CI 是被总流程调用的执行子系统，不定义整个提交流程、AI findings、人工审批或发布观察。

## 2. 目标与边界

CI 对当前 PR `head_sha` 给出可重复、可追溯、fail-closed 的机器结论：

- `pass`：所有适用 CI 门禁通过，且 required checks 与当前 head SHA 匹配；
- `fail`：代码、配置、测试、PR readiness、stage gate 或安全确定性检查失败；
- `blocked`：关键输入缺失、状态不完整或检查无法可靠判断。映射不明确在 report-only 阶段触发完整确定性 PR CI 回退，不单独解释为通过或阻断。

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

当前选择器先以 report-only 运行。路径映射明确时，它记录最小确定性 PR 检查集；路径未映射时，记录诊断并回退到完整确定性 PR CI，单独的未映射状态不阻断合并。base/head 缺失、head SHA 不匹配或选择器无法可靠读取输入时，artifact 标记 `blocked`；当前旧版完整 PR 检查仍是 required，report-only job 本身不改变 Branch Protection。完整回退只包含 PR 的 lint、离线测试、平台专项、typecheck、安全和 Docker 检查，不包含 Harness/Evaluation 长测、真实 LLM 或日跑。

## 4. CI 门禁

### R1：PR readiness

每个 PR 都运行 `check_pr_ready.py`。它检查基线、提交格式、敏感配置路径、文档语料基线和仓库规定的 PR 阻断项。文档变更还必须运行 git-docs evaluation；baseline 不干净时 readiness 失败。

### R2：变更相关检查

CI 根据 Registry 和 changed files 选择最小安全检查集：格式、语法和 lint；受影响单测、导入、Schema 或最小离线回归；配置、工作流或安全边界变更的专项检查；以及适用的 Docker 或跨仓契约 smoke。当前阶段只生成 report-only scope artifact；映射明确时记录相关 subset，映射不明确时记录完整确定性 PR CI 回退。只有观察期证明没有漏选且有足够耗时收益后，才允许把选择结果接入 PR gate。

### R3：阶段 gate

只有代码、配置或 `progress.yaml` 的阶段完成声明发生变更时，CI 才调用对应方向的 stage gate。阶段 gate 的命令、输入、状态字段和 evidence 由方向 Spec 与唯一 progress source 定义；CI 不重新解释阶段内容，也不把 Harness 阶段完成写成 CI 统一进度。

阶段 gate 缺失、取消、超时、退出非零、head SHA 不匹配或 evidence 不可读取时，CI 结果为 `fail` 或 `blocked`。普通文档编辑没有阶段状态变化时，不触发阶段 gate，只执行适用的文档和语料检查。

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
- 完整确定性回退失败、阶段 gate 失败或 required 输入缺失时，CI fail closed；
- `check_pr_ready.py`、lint、受影响单测和适用 stage gate 都能在当前 head SHA 上复核；
- scope selector 在固定样本上记录映射、未映射路径、回退范围和排除的 Evaluation/Harness workflow；
- 未映射路径不会静默缩减检查，也不会把长时 Evaluation/Harness 任务带入普通 PR 回退；
- required check 名称稳定且最终只有 `CI / PR gate` 作为合并聚合器；
- CI 文档不定义 AI findings、审批或发布流程；
- CI 文档不重复定义 Harness 的评分、Fixture、Replay 或 Episode 语义；
- docs 变更遵守 git-docs evaluation 和 baseline 规则。

## 7. 相关入口

- [AI 审核与变更保障 Spec](../ai-review/spec.md)
- [CI 子系统迁移计划](redesign-plan.md)
- [Harness 构建与统一契约 Spec](../harness/spec.md)
- [Spec 注册表](../registry.yaml)
- [PR 就绪审计](../../../scripts/ci/check_pr_ready.py)
- [测试工作流](../../../.github/workflows/test.yml)
