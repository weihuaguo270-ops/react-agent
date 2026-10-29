# CI 变更风险策略

## 1. 目的

本文定义代码提交后的机器风险评估，不定义业务验收、评测评分或生产 SLA。它把 CI、AI 审核和安全审核的结果整理成可供人工审批使用的风险证据。

风险评估必须绑定当前 PR 的 `head_sha`。新 commit 推送后，旧的机器结论、风险结论和人工审批不得继续用于合并。

## 2. 输出契约

风险评估至少输出以下字段：

```json
{
  "schema_version": "ci-risk/v1",
  "head_sha": "<current-pr-head>",
  "machine_result": "pass|fail|blocked",
  "risk_level": "low|medium|high|critical",
  "findings": [],
  "required_approvals": [],
  "evidence": []
}
```

- `machine_result` 继续使用 CI Spec 的 `pass`、`fail`、`blocked`，不把风险等级混入测试退出码；
- `risk_level` 表示变更需要的审查强度，不表示测试是否通过；
- `findings` 必须包含来源、严重程度、文件或 job 定位和证据入口；
- `required_approvals` 由审批策略根据风险等级生成；
- `evidence` 记录 workflow run、artifact 和审查结论的来源。

## 3. 风险分级

路径分类是最低风险基线；实际发现只能提升风险，不能因为自动检查通过而降低风险。

| 等级 | 默认变更范围 | 典型升级条件 |
|---|---|---|
| `low` | 文档、测试、非运行时样例和本地开发辅助配置 | AI 或安全审核发现运行时、权限或敏感信息影响 |
| `medium` | 应用逻辑、API、Schema、普通依赖和 Harness 代码 | 影响公共契约、数据格式或跨模块行为 |
| `high` | CI workflow、认证授权、Secret 使用、部署配置、数据迁移 | 权限扩大、可信边界变化、生产路径或安全规则变化 |
| `critical` | Branch Protection、发布凭据、生产基础设施和大范围权限提升 | 可能绕过审批、写入受保护分支或暴露凭据 |

无法根据路径和发现可靠分类时，风险评估为 `blocked`，并要求人工指定 owner 和处理方式；不得默认为 `low`。

## 4. 三类机器审核

### 4.1 CI

CI 负责确定性检查：PR readiness、lint、受影响单测、类型、Schema、Docker 和适用 stage gate。CI 只报告当前 head 的 `pass`、`fail` 或 `blocked`，不解释业务质量，也不替代人工审批。

### 4.2 AI 审核

AI 只检查当前 diff 及其相关 Spec、测试和配置，详细标准、问题格式和复核流程见 [AI 代码审核策略](ai-review-policy.md)。重点输出：

- 代码与 Spec 或接口契约不一致；
- 明确的逻辑错误、遗漏的失败路径和回归风险；
- 变更影响范围和建议风险等级；
- 需要人工确认但无法自动判定的问题。

AI 审核不得创建、批准或合并 PR。AI 无法确定的问题必须标记为 `review_required` 并提升人工审批要求；AI 没有发现问题不能替代人工批准。AI 审核结论只作为风险输入，不直接改变 CI 的确定性退出码。

### 4.3 安全审核

安全审核覆盖 Secret、依赖漏洞、Workflow 权限、`pull_request_target`、不可信代码执行、容器边界和 Branch Protection 操作。高危或严重安全发现直接产生 `fail` 或 `blocked`，不能用普通维护者审批绕过。

## 5. 风险聚合

风险聚合器读取三类审核的结构化结果，使用以下规则：

1. 任一确定性检查失败，`machine_result=fail`；
2. 输入缺失、head SHA 不匹配、审核结果不可读或风险无法分类，`machine_result=blocked`；
3. 任何发现只能保持或提升 `risk_level`；
4. 机器审核全部通过不等于可以合并，仍需满足 [审批策略](approval-policy.md)；
5. 完整评测、日跑和真实 LLM evidence 不直接改变普通 PR 的机器结论。

## 6. 证据要求

风险结果必须保存：当前 `head_sha`、base SHA、PR 编号、changed files、各审核 run、工具版本、发现及其定位、聚合时间和 artifact 地址。历史运行只能作为背景证据，不能替代当前 head 的验证。
