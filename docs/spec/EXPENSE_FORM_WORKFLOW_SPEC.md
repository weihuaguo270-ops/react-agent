# Expense 表单与审批 Workflow 规格

## 1. 文档状态

本文定义 `expense` 下一阶段的产品与实现任务：把当前“传入结构化 `claim` 并返回规则决策”的 API 能力，扩展为可校验、可保存、可提交、可人工审批和可审计的表单型 Workflow。

本文是实现与验收规格，不代表已实现能力，也不构成真实财务合规、付款或生产 SLA 承诺。

现状基线与规则决策契约见 [`EXPENSE_WORKFLOW_DECISION_SPEC.md`](EXPENSE_WORKFLOW_DECISION_SPEC.md)。人工接管、工单分派、通知和 SLA 另见 [`EXPENSE_HUMAN_HANDOFF_SPEC.md`](EXPENSE_HUMAN_HANDOFF_SPEC.md)。本规格只增加表单任务和审批生命周期，不改变现有决策码的含义。

本规格是 Expense claim 生命周期的权威规格：表单 Workflow 是父流程，`submit` 后调用决策 SPEC 的 `expense_claim_review@1` 子流程，再由本规格的 `route_review` / `resolve_review` 决定是否创建审批或人工工单并改变 claim 状态。决策子流程不得直接把 claim 写成 `approved`、`rejected` 或 `escalated`。

接口边界固定如下：本规格的 `/v1/expense/reviews/{approval_id}/resolve` 是 Expense 领域审批入口；现有 `/v1/approvals/{approval_id}` 只作为通用 CONFIRM 凭据兼容接口，不替代 Expense 审批记录。人工接管的 `/v1/expense/cases/{case_id}/resolve` 只完成工单处理并绑定审批，不绕过本审批入口。

## 2. 当前边界

当前 `expense` 支持：

- `POST /v1/chat` 携带 `app=expense` 和结构化 `claim`；
- `POST /v1/skills/run` 调用 `expense_claim_review`；
- 确定性规则决策、政策引用和 `refused` 结果。

当前不支持：

- 独立表单 UI；
- 草稿保存和恢复；
- 独立的报销任务 ID；
- `submitted / under_review / approved / rejected` 生命周期；
- 审批人身份、意见和审批历史持久化；
- 付款或外部财务系统写入。

因此，结构化 `claim` 目前只是“表单型重试”的输入形式，不应描述为完整表单提交或审批闭环。

## 3. 目标与非目标

### 3.1 目标

1. 提供一个独立的 Expense 表单页面，能创建、编辑、校验和提交报销单。
2. 提供与 UI 对齐的 HTTP 任务接口，支持草稿、提交、查询、审批和拒绝。
3. 将现有规则决策 Workflow 作为提交后的唯一决策入口。
4. 对所有状态变化保存操作者、时间、原因、决策码和幂等信息。
5. 对需要人工确认的决策使用现有异步审批语义；未批准不得产生外部副作用。
6. 保留现有 `/v1/chat` 和 `expense_claim_review` 的兼容行为，作为只读决策接口。

### 3.2 非目标

- 自动打款、发票真伪核验、税务申报或企业财务系统集成；
- 多租户组织权限、复杂代理审批、会签和转审规则；
- 用 LLM 替代确定性政策规则；
- 允许模型直接修改报销单或绕过审批接口；
- 在本阶段把普通聊天入口改造成表单任务入口。

## 4. 角色与职责

| 角色 | 能力 | 不能做什么 |
|------|------|------------|
| 申请人 | 创建/编辑自己的草稿，提交报销单，查看结果 | 不能修改已提交单据的核心金额、类目或凭证状态 |
| Agent/规则 Workflow | 校验字段、读取政策、生成结构化决策和审批建议 | 不能伪造审批人、自动批准需人工复核的例外、写外部财务系统 |
| 审批人 | 查看待审单据、批准、拒绝、填写意见 | 不能修改原始 claim；拒绝后必须重新提交新版本 |
| 财务/运营 | 查询审计记录和状态，处理升级单 | 本阶段不执行付款或清账 |

Agent 负责“解析、校验、决策和建议”；人负责“业务审批、例外确认和最终授权”。

## 5. 领域数据模型

### 5.1 ExpenseClaim

```json
{
  "claim_id": "clm_01J...",
  "version": 1,
  "applicant_id": "user_123",
  "category": "餐饮",
  "amount": 128.0,
  "currency": "CNY",
  "occurred_on": "2026-10-11",
  "merchant": "示例餐厅",
  "description": "客户会议餐费",
  "has_receipt": true,
  "receipt_refs": ["upload_123"],
  "pre_approved": false,
  "status": "draft",
  "idempotency_key": "claim-create-123"
}
```

表单 Claim 的 MVP 必填字段是 `category`、`amount`、`currency`、`occurred_on`、`description`、`has_receipt`。金额必须为有限非负数；日期必须是 ISO 日期；`receipt_refs` 在 `has_receipt=true` 时至少包含一个引用。

旧 `/v1/chat` 和 `expense_claim_review` 允许只提供决策所需的 legacy Claim（至少 `category`、`amount`、`has_receipt`、`pre_approved`）。进入表单 `submit` 前必须通过归一化补齐表单字段；无法补齐时返回 `invalid_claim`，不得调用决策子流程。两种输入最终必须产生同一结构化 policy facts 和 decision 契约。

### 5.2 ApprovalRecord

```json
{
  "approval_id": "apr_01J...",
  "claim_id": "clm_01J...",
  "claim_version": 2,
  "decision": "approve",
  "approver_id": "manager_456",
  "comment": "符合部门额度",
  "created_at": "2026-10-11T10:00:00Z"
}
```

审批记录只能追加，不能覆盖。审批必须绑定 `claim_id + version + decision_hash`，避免批准后单据内容被替换。`decision` 仅允许 `approve`、`reject`、`escalate`；`escalate` 只产生更高层级人工处理，不是批准结果。

### 5.3 AuditEvent

至少记录：`event_id`、`claim_id`、`claim_version`、`event_type`、`actor_type`、`actor_id`、`request_id`、`idempotency_key`、`created_at` 和结构化 `metadata`。

## 6. 状态机

```text
draft
  -> submitted
  -> cancelled

submitted
  -> validating

validating
  -> needs_correction
  -> under_review
  -> approved
  -> rejected
  -> escalated

needs_correction
  -> submitted (new version)

under_review
  -> approved
  -> rejected
  -> escalated

escalated
  -> under_review       # 创建/接收更高层级审批或人工工单后继续处理
  -> needs_correction   # 申请人必须补充材料

approved / rejected / cancelled
  -> terminal
```

约束：

- 只有 `draft` 和 `needs_correction` 可编辑；
- `submitted` 后冻结本版本的核心字段；修正必须创建新版本；
- `approved`、`rejected`、`cancelled` 是终态，重复请求返回原状态，不重复写审计事件；
- `escalated` 表示需要更高层级人工处理，是非终态；不得自动转为 `approved`。只有带合法审批记录的 `resolve_review` 才能进入批准或拒绝终态；
- 所有状态迁移必须经过允许的转移表，非法转移返回 `invalid_state_transition`。

## 7. Workflow 节点

| 节点 | 作用 | 是否写入 | 人工确认 |
|------|------|----------|----------|
| `create_draft` | 创建空表单或初始 claim | 创建草稿 | 否 |
| `update_draft` | 更新可编辑字段并递增版本 | 更新草稿 | 否 |
| `validate_claim` | 校验类型、必填项、附件引用 | 写校验结果 | 否 |
| `load_policy_facts` | 读取政策和额度版本 | 否 | 否 |
| `decide_claim` | 调用 `expense_claim_review@1` 决策子流程并取得结构化决策 | 写决策审计 | 否 |
| `route_review` | 根据决策码、`review_required` 和 handoff 条件选择自动拒绝、审批或人工工单 | 创建待审记录/工单并更新非终态 | 需要时 |
| `resolve_review` | 记录批准/拒绝/升级 | 写审批和状态 | **是** |
| `finalize` | 返回当前版本、决策和审计摘要 | 否 | 否 |

`decide_claim` 只能输出结构化决策；`route_review` 和 `resolve_review` 才能改变任务状态。规则模型不得直接调用 `resolve_review`。当决策输出包含 `handoff` 时，`route_review` 必须把其中的 `reason_code`、`risk_level`、`amount_band`、`decision_hash` 传给人工接管 Workflow；不得由路由层重新猜测。

## 8. HTTP 契约

所有接口沿用现有 Bearer 鉴权、`request_id` 和结构化错误 envelope。写接口必须支持 `Idempotency-Key`。

| 方法 | 路径 | 用途 |
|------|------|------|
| `POST` | `/v1/expense/claims` | 创建草稿，返回 `claim_id` |
| `GET` | `/v1/expense/claims/{claim_id}` | 查询当前版本和状态 |
| `PATCH` | `/v1/expense/claims/{claim_id}` | 更新草稿或待修正版本 |
| `POST` | `/v1/expense/claims/{claim_id}/submit` | 冻结版本并启动 Workflow |
| `GET` | `/v1/expense/claims/{claim_id}/events` | 查询追加式审计事件 |
| `GET` | `/v1/expense/reviews` | 查询当前用户有权查看的待审单 |
| `POST` | `/v1/expense/reviews/{approval_id}/resolve` | 人工批准、拒绝或升级 |

提交响应示例：

```json
{
  "claim_id": "clm_01J...",
  "version": 2,
  "status": "under_review",
  "decision": "approve_finance",
  "review_required": true,
  "approval_id": "apr_01J...",
  "request_id": "req_01J..."
}
```

`decision` 是决策码（例如 `approve_finance`），`status` 是 claim 生命周期状态；二者不可互换。`review_required=true` 时提交响应必须是 `under_review` 或 `escalated`，不能返回 `approved`。

审批接口只接受：

```json
{
  "decision": "approve",
  "comment": "符合政策",
  "expected_version": 2
}
```

幂等键按业务作用域分别定义，不能跨作用域复用后静默改变含义：

| 作用域 | 推荐组成 | 重放结果 |
|--------|----------|----------|
| claim 写接口 | `request:<claim_id>:<operation>:<client_key>` | 返回同一 claim/version 结果 |
| 决策子流程 | `decision:<claim_id>:<version>:<policy_version>` | 返回同一 decision 和 decision audit |
| 审批决议 | `approval:<approval_id>:<expected_version>:<decision>` | 返回同一 approval record；版本或决策冲突失败 |
| 人工工单 | `handoff:<claim_id>:<version>:<reason_code>` | 复用同一活动 case |

任何作用域中同一幂等键对应不同 claim、版本或业务内容都返回 `idempotency_conflict`，不产生状态或审计副作用。

## 9. 表单 UI

### 9.1 MVP 页面

新增独立 Expense 页面，不把表单塞进通用聊天 UI。页面至少包含：

- 类目选择、金额、币种、发生日期、商户、说明；
- 有无凭证切换和凭证引用；
- 预审批状态；
- 保存草稿、提交审核、取消按钮；
- 字段级错误、状态标签、决策结果和审批意见；
- 提交后只读展示当前版本和审计时间线。

### 9.2 UI 约束

- 前端校验只改善交互，后端仍是唯一校验权威；
- 提交按钮必须携带幂等键，重复点击不能创建多个任务；
- `under_review`、`approved`、`rejected` 状态下禁用核心字段编辑；
- 审批操作必须显示单据版本、决策依据和风险提示；
- UI 不显示“已付款”或“已入账”，除非未来接入真实外部系统并有独立证据。

## 10. 持久化与安全边界

- Expense 任务、claim 版本、审批记录和审计事件必须持久化；不能只放进进程内 `ExpenseLedger`。正式业务事实来源统一为 PostgreSQL；`ExpenseLedger` 仅用于离线评测或 legacy adapter。
- 推荐复用项目 PostgreSQL 任务存储模式；Redis 只作为异步队列，不作为业务事实来源。
- `resolve_review`、状态变更和外部通知属于副作用，须经过权限闸门；默认生产模式使用异步人工审批。
- 审批凭据必须绑定 claim 版本和决策指纹，过期、拒绝、重复使用都失败关闭。
- 附件只保存受控引用和元数据；本阶段不承诺文件内容扫描或 OCR。
- 任何越权 claim 访问返回统一 `not_found` 或授权错误，不泄露其他申请人的存在性。

## 11. 错误码

至少支持：

| 错误码 | 含义 |
|--------|------|
| `invalid_claim` | 字段缺失、类型错误或附件引用无效 |
| `claim_not_editable` | 当前状态不可编辑 |
| `invalid_state_transition` | 状态迁移不允许 |
| `policy_unavailable` | 政策事实不可读取，失败关闭 |
| `review_required` | 需要人工审批，返回 `approval_id` |
| `approval_expired` | 审批已过期 |
| `approval_version_mismatch` | 审批对应版本与当前版本不一致 |
| `idempotency_conflict` | 同一幂等键对应不同请求 |
| `forbidden_claim_access` | 无权访问该单据 |
| `external_write_not_supported` | 本阶段不支持付款或外部系统写入 |

## 12. 分阶段任务

### P0：契约冻结

- 固定字段、状态、错误码和状态转移表；
- 将现有 `claim` 决策接口标记为 legacy/read-only compatibility；
- 为 dev/golden/held_out 样例补充状态和版本字段。

退出标准：契约测试覆盖合法/非法 claim、状态迁移和错误码；旧 `/v1/chat` 行为无回归。

### P1：后端任务与持久化

- 新增 Expense claim/review/event 数据模型和 PostgreSQL store；
- 实现创建草稿、查询、更新草稿、提交接口；
- 实现版本号、幂等键、访问控制和追加式审计；
- 将现有决策 Workflow 接到 `submit` 后路径。

退出标准：重启后任务可查询；重复提交不重复创建；版本冲突不写入；审计事件完整。

### P2：人工审批闭环

- 实现待审列表和审批决议接口；
- 绑定 `claim_version + decision_hash`；
- 接入现有异步审批/权限闸门；
- 覆盖批准、拒绝、升级、过期、重复使用和版本不匹配。

退出标准：未经批准不进入批准终态；拒绝和升级可审计；审批失败关闭。

### P3：独立表单 UI

- 新增 Expense 页面和表单状态管理；
- 接入字段校验、草稿保存、提交、轮询/刷新状态和审批意见展示；
- 处理网络失败、重复提交、过期版本和无权限状态；
- 保持通用聊天页与 Expense 表单页职责分离。

退出标准：浏览器端完成“新建 → 保存 → 编辑 → 提交 → 待审 → 审批结果”主路径；移动宽度无字段重叠。

### P4：业务验收与上线门禁

- 增加端到端业务评测，分别统计 dev/golden/held_out；
- 断言最终状态、决策码、审计事件和人工接管条件；
- 增加权限、租户边界、幂等、重启恢复和失败关闭测试；
- 更新 `DEPLOY.md`、`APPLICATION_DIRECTION.md`、演示和 API 示例。

退出标准：所有必需测试通过；held_out 单独报告；没有把本地 demo 证据描述为生产财务能力。

## 13. 文件级任务清单

| 文件/目录 | 任务 |
|-----------|------|
| `src/react_agent/apps/expense/` | 新增 claim/review/event 契约、Workflow adapter 和持久化接口 |
| `src/react_agent/server/fastapi_app.py` | 注册 `/v1/expense/*` 路由和统一错误处理 |
| `src/react_agent/server/static/` | 新增独立 Expense 表单页面或静态入口 |
| `src/react_agent/server/task_manager.py` / PostgreSQL store | 复用或扩展任务生命周期存储，不把业务事实放入 Redis |
| `src/react_agent/safety/permissions.py` | 登记审批决议和状态变更的权限等级 |
| `tests/` | 契约、状态机、HTTP、审批、幂等、重启和 UI smoke 测试 |
| `docs/operations/DEPLOY.md` | 增加接口、环境变量、审批配置和持久化要求 |
| `docs/guide/APPLICATION_DIRECTION.md` | 将 Expense 从 demo 边界更新为已实现/未实现分层 |
| `demos/demo_expense_workflow.py` | 继续调用同一 Workflow，不复制业务规则 |

## 14. 发布边界

在 P4 完成前，对外只能描述为：

> Expense 支持结构化 claim 的离线政策决策和人工审批 Workflow 原型；表单 UI、持久化任务和外部付款不属于当前已实现能力，除非对应里程碑和验收证据已完成。

任何“自动报销”“已付款”“财务系统已入账”等表述都需要独立的外部系统集成和验收证据。

## 15. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-10-11 | S0 契约统一：表单 Workflow 作为父流程；统一 escalated、审批入口、Claim 归一化、幂等键和 PostgreSQL 事实来源 |
