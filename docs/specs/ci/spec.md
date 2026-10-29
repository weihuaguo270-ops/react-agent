# CI 合并门禁 Spec

## 1. 文档状态

**状态：** Proposed
**版本：** v1.3
**最后更新：** 2026-10-24
**负责人：** 仓库维护者

本文档只定义 CI 如何判断当前代码或配置变更能否合入 `main`。迁移顺序和观察窗口见 [redesign-plan.md](redesign-plan.md)。各业务方向的阶段内容由对应 Spec 定义；Evaluation Harness 的执行、评分和证据由 [Harness Spec](../harness/spec.md) 定义。

## 2. 目标与边界

### 2.1 目标

对当前 PR head SHA 给出可重复、可追溯、fail-closed 的合并结论。CI 的结果只有：

- `pass`：所有适用门禁通过，且 required checks 与当前 head SHA 匹配；
- `fail`：代码、配置、测试、PR ready、stage gate 或安全检查失败；
- `blocked`：输入缺失、状态不完整、映射不明确或检查无法可靠判断。`blocked` 不得被 Branch Protection 当作通过。

### 2.2 CI 负责的对象

- 当前 PR 的代码、配置、工作流和 Spec/进度变更；
- 变更路径到门禁规则的选择；
- lint、受影响单测和最小回归；
- `scripts/ci/check_pr_ready.py` 的 PR 就绪审计；
- 代码或配置变更触发的方向 stage gate；
- required checks 的聚合、当前 head SHA 绑定和安全边界。

### 2.3 CI 不负责的对象

- Evaluation Harness 的 Fixture、题集、Runner、评分、Replay、Episode、Trajectory 或 artifact 语义；
- Runtime Harness 的 ToolCall、RuntimeEpisode 和运行时协议；
- 业务方向的验收内容、业务进度或生产 SLA；
- 日跑、完整评测矩阵、真实 LLM 质量结论和长期趋势。它们可以被 CI 触发或链接为 evidence-only，但不改变普通 PR 的合并结论；日跑默认只读并输出 artifact，不提交仓库文件、创建 PR 或自动合并。

CI 可以调用 Harness 或方向 Spec 暴露的 gate 命令，但只消费其退出码和结构化摘要，不复制其测试场景、评分逻辑或阶段进度。

风险分级、AI 审核和人工审批分别由 [变更风险策略](risk-policy.md)、[AI 代码审核策略](ai-review-policy.md) 与 [人工审批策略](approval-policy.md) 定义。CI 提供当前 head 的确定性机器结论和风险证据，不把 AI 审核结果直接解释为通过，也不替代维护者审批。

## 3. 输入、选择与输出

每次 PR gate 必须绑定：

1. `base_sha`、`head_sha` 和 PR 编号（若来自 PR 事件）；
2. changed files 及事件类型；
3. Registry 中匹配的 rule ID、适用性和 gate 入口；
4. workflow/job 结论、退出码和可读取的 artifact。

Registry 只记录 `path_globs -> rule_id -> gate entrypoint` 及执行约束。它不记录 Harness 的题目、评分或每个阶段的测试明细。方向 Spec 自己拥有 stage gate 命令和 evidence 结构，CI 只负责判断是否触发并聚合结果。

当路径没有安全映射时，CI 必须运行固定的 unmapped-safety 子集并将总状态置为 `blocked`，直到补充映射或有带原因、审批角色和到期日的一次性例外。不得静默放行，也不得在普通 PR 中无界回退到全量评测。

## 4. 合并门禁

### R1：PR readiness

每个 PR 都运行 `check_pr_ready.py`。它检查工作区/基线、提交格式、敏感配置路径、文档语料基线和本仓库规定的 PR 阻断项。文档变更还必须按仓库规则运行 git-docs evaluation；baseline 不干净时 readiness 失败。

### R2：变更相关检查

CI 根据 Registry 和 changed files 选择最小安全检查集：

- 格式、语法和 lint；
- 受影响的单测、导入、Schema 或最小离线回归；
- 配置、工作流或安全边界变更的专项检查；
- Docker 或跨仓契约 smoke（仅在路径映射或 P0 规则适用时）。

映射明确时只运行相关 subset。映射不明确时使用 unmapped-safety 并保持 `blocked`，不把“跑了全量”解释为映射完成。

### R3：阶段 gate

只有代码、配置或 `progress.yaml` 的阶段完成声明发生变更时，CI 才调用对应方向的 stage gate。阶段 gate 的命令、输入、状态字段和 evidence 由该方向的主 Spec 与唯一 progress source 定义；CI 不重新解释阶段内容，也不把 Harness 的阶段完成写成 CI 的统一进度。

阶段 gate 缺失、取消、超时、退出非零、head SHA 不匹配或 evidence 不可读取时，合并结论为 `fail` 或 `blocked`。普通文档编辑没有阶段状态变化时，不触发阶段 gate，只执行适用的文档和语料检查。

### R4：required checks 聚合

迁移目标是始终创建两个稳定 job：`CI / PR readiness` 和 `CI / PR gate`。前者输出 readiness 和选择结果；后者聚合 readiness、R2、R3、安全检查和映射状态，是唯一的合并硬门禁。条件 job、完整矩阵、日跑和阶段报告不直接加入 Branch Protection。

聚合器必须把 `failure`、`cancelled`、`timed_out`、`action_required`、缺失输入、状态缺失和 head SHA 不匹配解释为 `fail` 或 `blocked`，不能解释为通过。迁移完成前的旧 required checks 由迁移计划管理，不在本 Spec 中重复维护历史清单。

### R5：安全与权限

普通 PR 使用最小 job 权限；fork PR 不读取写入 Secret，不执行 `pull_request_target` checkout 的不可信代码。执行不可信代码的 job 不得写仓库或修改 Branch Protection。Actions、镜像和外部依赖按仓库安全规则固定版本。安全检查失败直接阻断合并。

### R6：风险与人工审批

CI 必须为当前 `head_sha` 生成机器结论和风险证据。风险等级可以由 changed files、CI/AI/安全发现共同提升，但不能把风险等级当作测试通过状态。机器检查全部通过后，仍须按照 [人工审批策略](approval-policy.md) 满足对应风险等级的 owner 和安全审批；新 commit 会使旧机器结论和审批失效。

## 5. 本地、PR 与外部证据

| 检查层 | 目的 | 结论 |
|---|---|---|
| 本地提交前 | 快速 lint、受影响单测、配置/Schema 校验 | 提交前反馈，不替代 CI |
| PR CI | 当前 diff 的 readiness、subset、stage gate 和 required checks | 决定能否合入 `main` |
| 日跑/发布/评测 | 完整矩阵、长时方差、真实 LLM、跨环境或 Harness 质量 | evidence-only artifact，除非另有发布 gate |

外部 evidence 必须保留自己的运行身份、版本、输入和 artifact provenance；历史、fixture/mock、held-out 和生产结果不得混为当前 PR 的 `pass`。

## 6. 最小验收标准

- 变更路径明确时，PR 只运行对应 subset 和必要门禁；
- 映射缺失、阶段 gate 失败或 required 输入缺失时，聚合器 fail closed；
- `check_pr_ready.py`、lint、受影响单测和适用 stage gate 都能在当前 head SHA 上复核；
- required check 名称稳定且始终创建，只有 `CI / PR gate` 作为合并聚合器；
- 风险结果绑定当前 head SHA，并能追溯到 CI、AI 和安全证据；
- 高风险变更需要对应 owner/安全审批，安全阻断不能由普通审批绕过；
- CI 文档不重复定义 Harness 的评分、Fixture、Replay 或 Episode 语义；
- docs 变更遵守 git-docs evaluation 和 baseline 规则。

## 7. 相关入口

- [CI 迁移计划](redesign-plan.md)
- [Harness 构建与统一契约 Spec](../harness/spec.md)
- [Spec 注册表](../registry.yaml)
- [PR 就绪审计](../../../scripts/ci/check_pr_ready.py)
- [测试工作流](../../../.github/workflows/test.yml)
- [变更风险策略](risk-policy.md)
- [AI 代码审核策略](ai-review-policy.md)
- [人工审批策略](approval-policy.md)
