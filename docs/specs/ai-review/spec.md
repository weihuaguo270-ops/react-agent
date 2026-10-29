# AI 审核与变更保障 Spec

## 1. 文档状态

**状态：** Proposed
**版本：** v1.0
**最后更新：** 2026-10-29
**负责人：** 仓库维护者

本文档是代码变更保障流程的顶层 Spec。它编排 AI 审核、CI、Security、Harness/Evaluation、人工审批以及合并后的发布观察。CI 是确定性执行子系统，不拥有整个提交流程的架构主导权。

## 2. 目标与边界

AI 审核负责把当前变更的目标、diff、Spec、测试和机器证据整理为可复核的风险结论。它不替代 CI 的确定性门禁、Security 的安全结论、Harness/Evaluation 的评测语义或维护者的最终审批。

AI 审核包含：

- PR 前的离线审核；
- PR 创建和更新后的 report-only 审核；
- 合并前的 findings、风险和审批编排；
- 合并后的发布观察、回滚和审计证据关联。

AI 审核不包含：

- CI lint、单测、stage gate 或 required check 的内部实现；
- Harness/Evaluation 的 Fixture、评分、Replay、Episode、Trajectory 或长期质量指标；
- Secret 读取、Branch Protection 修改、自动批准/合并或生产系统写入。

## 3. 生命周期

### 3.1 PR 前

固定工作树或候选 diff，收集相关 Spec、受影响测试和本地 CI 等价检查，生成离线报告。该报告帮助作者修改，不参与合并门禁。

### 3.2 PR 中

以 PR 的 `base_sha`、`head_sha` 和事件类型为审核身份，收集 changed files、相关 Spec、CI 结果、Security 结果以及 Harness/Evaluation evidence 引用。第一阶段只输出 report-only artifact，不改变 Branch Protection。

### 3.3 合并前

聚合当前 head 的 AI findings、CI 结论、安全结论和人工审批要求。只有所有输入均绑定当前 head 且没有未关闭 blocker 时，才能形成可供合并流程消费的结论。AI 审核结论本身不等同于 GitHub required check。

### 3.4 合并后

关联合并 commit、发布渠道、feature flag、latest/stable 观察、回滚和审计证据。发布/部署细节由独立 Release/Deployment Spec 管理；AI 审核只负责编排和记录观察结果。

## 4. 子系统职责

| 子系统 | 职责 | 输出 |
|---|---|---|
| AI Review | diff 风险发现、最小复现、findings 和审核状态 | `pass/review_required/fail/blocked` |
| CI | lint、受影响测试、PR readiness、stage gate、required checks、安全确定性检查 | `pass/fail/blocked` 与结构化证据 |
| Security | Secret、依赖、权限、workflow 和不可信代码边界检查 | 安全 findings 与安全结论 |
| Harness/Evaluation | Fixture、Runner、评分、Replay、Episode 和长期 evidence | evidence-only 评测 artifact |
| 人工审批 | 接受风险、裁决争议和最终批准 | reviewer、风险等级、审批记录 |
| Release/Deployment | 发布、观察、回滚和渠道管理 | 发布观察与回滚证据 |

CI 可以被 AI Review 调用，但 CI 必须能够在没有 AI Review 的情况下产生自身确定性结论。Harness/Evaluation 只提供 evidence，不被本 Spec 重新定义评分语义。

## 5. 输入与 artifact 契约

每次审核必须记录：

- `base_sha`、`head_sha`、PR 编号和事件类型；
- changed files、相关 Spec、测试命令和 CI/Security/Harness evidence 引用；
- 审核模型、版本、提示模板、工具和时间；
- findings、风险等级、作者处理状态和人工审批要求。

结构化审核 artifact 的最小字段为（机器可读契约见 [artifact.schema.json](artifact.schema.json)）：

```json
{
  "schema_version": "ai-review/v1",
  "base_sha": "<base>",
  "head_sha": "<head>",
  "pr_number": 123,
  "status": "pass|review_required|fail|blocked",
  "findings": [],
  "risk_level": "low|medium|high|critical",
  "ci": {"status": "pass|fail|blocked", "head_sha": "<head>"},
  "security": {"status": "pass|fail|blocked", "head_sha": "<head>"},
  "required_approvals": [],
  "evidence": []
}
```

每条 finding 至少包含 `id`、`severity`、`confidence`、`category`、定位、触发条件、预期、实际、证据、建议和 `status`。缺少定位或证据的问题只能进入 `review_required`，不能直接形成确定性阻断。

## 6. 状态与风险聚合

- `pass`：当前 head 的输入完整；没有未关闭 blocker/high，也没有需要人工裁决的安全或权限问题；CI 和 Security 输入均为 pass。
- `review_required`：存在低置信度、范围不清、作者与审核结论不一致或需要人工裁决的问题。
- `fail`：存在已确认的 blocker，或未处理的高危安全问题，或 CI 确定性检查失败。
- `blocked`：artifact 缺失、字段不完整、SHA 不匹配、输入不可读或无法可靠分类。`blocked` 不得解释为通过。

风险等级只能保持或提升，不能因为检查通过而降低。人工审批要求由风险策略产生，但审批记录必须由真实 reviewer 完成。

## 7. 失效与重新审核

审核和审批均绑定 `base_sha/head_sha`。发生以下任一事件时，旧审核失效并必须重新审核：

- 新 commit 推送；
- rebase 或 base 分支更新；
- changed files、相关 Spec、CI 配置或安全策略发生变化；
- 合并前发现未关闭 blocker 或输入状态变化。

历史 artifact 只能作为背景证据，不能替代当前 head 的验证。

## 8. AI 审核实施阶段

### A0：架构与契约

冻结生命周期、职责边界、artifact schema、状态语义和 SHA 失效规则。

### A1：离线审核

使用固定 diff、相关 Spec 和测试上下文生成结构化审核报告，支持最小复现和人工复核。

### A2：PR report-only

在当前 head SHA 上运行并发布报告，不改变合并门禁或 Branch Protection。

### A3：风险与审批编排

接入 CI、Security 和人工审批要求，聚合 findings、风险等级和 required reviewers。

### A4：合并与合并后观察

接入合并队列、发布观察、feature flag、回滚和审计证据；具体部署实现由 Release/Deployment Spec 管理。

## 9. 验收标准

- AI Review、CI、风险策略之间没有重复或相反的权威定义；
- CI 可独立产生确定性 `pass/fail/blocked`，并作为 AI Review 输入；
- AI findings、CI、Security 和审批均绑定当前 `head_sha`；
- 新 commit、rebase 或 base 更新使旧审核失效；
- 缺失 artifact、SHA 不匹配和未关闭 blocker 不会被解释为通过；
- Harness/Evaluation 只提供 evidence，不被 AI Review 复制评分语义；
- 旧 CI 路径不再保留第二份政策正文；
- A2 report-only 完成前不新增 AI Review required check。

## 10. 相关文档

- [CI 执行子系统 Spec](../ci/spec.md)
- [CI 子系统迁移计划](../ci/redesign-plan.md)
- [AI 审核策略](ai-review-policy.md)
- [变更风险策略](risk-policy.md)
- [人工审批策略](approval-policy.md)
- [Harness 构建与统一契约 Spec](../harness/spec.md)
