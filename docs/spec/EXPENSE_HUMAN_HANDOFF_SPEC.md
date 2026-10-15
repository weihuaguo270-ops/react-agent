# Expense 人工接管、工单与队列分派规格

## 1. 文档状态

本文定义 `expense` 在表单与审批 Workflow 之后的人工接管扩展：当 Agent 或规则 Workflow 无法安全完成决策时，系统创建可追踪的人工工单，分派到有责任边界的队列，由人工认领、处理、升级并回写业务状态。

本文是下一阶段的实现与验收规格，不代表当前项目已经具备内置工单、自动分派、通知或 SLA 管理能力。当前已有的 `approval_id`、待审批记录和人工决议接口仍是轻量审批基础设施；本规格在其上增加工单和运营闭环。

相关规格：

- [`EXPENSE_WORKFLOW_DECISION_SPEC.md`](EXPENSE_WORKFLOW_DECISION_SPEC.md)：规则决策与决策节点；
- [`EXPENSE_FORM_WORKFLOW_SPEC.md`](EXPENSE_FORM_WORKFLOW_SPEC.md)：表单、claim 生命周期和审批接口。

本规格是表单父 Workflow 的后置人工接管子流程。`route_review` 只能把决策 SPEC 输出的结构化 `handoff` 转换为 case；它不得重新解释决策或直接改变 claim 终态。`case.resolve` 只完成工单处理，涉及 claim 批准/拒绝时必须调用并绑定表单 SPEC 的 `/v1/expense/reviews/{approval_id}/resolve` 记录。

## 2. 当前能力与缺口

当前项目可以：

- 在 `CONFIRM` 操作上创建待审批记录；
- 返回 `approval_id` 和 `awaiting_approval`；
- 通过审批接口批准、拒绝或授予一次/会话范围；
- 使用审批凭据重试原请求，并记录过期、拒绝和重复使用失败。

当前项目尚不能：

- 为人工接管创建独立工单 ID；
- 根据业务类型、组织或权限自动分派责任队列；
- 支持认领、转派、暂停、回退和队列负载查询；
- 发送站内、邮件或消息通知；
- 计算 SLA、超时提醒和自动升级；
- 把人工处理结果安全地绑定回 Expense claim 版本。

## 3. 目标与非目标

### 3.1 目标

1. 将 `human_handoff_conditions` 转换为结构化工单创建事件。
2. 为每个工单确定责任队列、优先级、截止时间和升级路径。
3. 让人工处理结果绑定 `claim_id`、`claim_version` 和 `decision_hash`。
4. 支持人工认领、转派、处理、升级和关闭，并保留追加式审计。
5. 在通知失败、队列不可用或 SLA 计算异常时失败关闭，不自动批准报销。
6. 与现有 `/v1/approvals` 兼容：审批记录是授权凭据，工单是运营跟踪对象，两者不能互相替代。

### 3.2 非目标

- 本阶段不接入真实付款、ERP、企业微信、钉钉或邮件供应商；
- 不实现通用 ITSM 平台、复杂会签、代理审批和跨租户组织目录；
- 不允许 Agent 自己选择审批人或绕过队列权限；
- 不把“通知已发送”当作“人工已批准”；
- 不以队列中有工单作为业务状态已经改变的证据。

## 4. 术语与边界

| 术语 | 含义 |
|------|------|
| `human_handoff_conditions` | 触发人工接管的条件，例如凭证需核验、规则未覆盖、金额超出自动处理范围 |
| `escalation` | 工单进入更高权限或更高专业级别队列的动作和结果 |
| 工单（case） | 可追踪的一次人工处理任务，拥有独立 `case_id` |
| 队列（queue） | 具有责任范围和访问策略的处理集合，例如 `finance_review` |
| 认领（claim） | 某个处理人暂时取得工单处理锁，不改变业务审批结果 |
| 审批记录（approval） | 对指定 claim 版本的批准/拒绝授权记录 |
| SLA | 从工单创建开始计算的响应/解决时限和升级规则 |

关键关系：

```text
Expense claim/version
        |
        +--> case (人工处理工单)
        |       +--> queue assignment
        |       +--> notifications
        |       +--> SLA timers
        |       +--> case events
        |
        +--> approval record (最终授权)
```

工单可以驱动人工处理，但只有合法的审批记录和状态转移才能改变 claim 的批准结果。`escalated` 永远是人工处理中的非终态；工单、通知或 SLA 事件都不能把它自动改为 `approved`。

## 5. 触发规则

### 5.1 必须创建工单的条件

至少覆盖：

- `claim` 字段或凭证需要人工核验；
- 政策规则未覆盖该费用类型；
- 政策事实冲突或政策版本不可确定；
- 金额、币种或风险超过自动决策阈值；
- 申请人对拒绝结果提出复核；
- Agent 生成 `human_handoff_conditions`；
- 审批人选择 `escalated`；
- 外部依赖不可用但不能安全拒绝或批准。

### 5.2 不得创建“假工单”的情况

- 普通只读政策问答；
- 字段缺失且申请人可以直接补齐的表单校验错误；
- 明确命中硬拒绝规则且无需人工例外判断；
- 已存在同一 claim 版本和同一触发指纹的活动工单。

重复触发必须返回既有 `case_id`，不能生成重复队列任务。

决策到工单的最小映射固定如下：

| 决策输出 | `reason_code` 来源 | claim 处理 |
|----------|-------------------|------------|
| `review_required=true` | 决策输出的 `handoff.reason_code` | 进入 `under_review` 或 `escalated`，等待审批/人工处理 |
| `rule_result=not_covered` | `policy_not_covered` 或更具体的受控码 | 不得自动批准，创建人工工单 |
| `decision=escalated` | `escalation_requested` 或输出中的受控码 | 保持 `escalated`，创建/复用工单 |
| 缺失必填字段 | 不创建工单 | 返回表单 `invalid_claim`，由申请人修正 |

`reason_code`、`risk_level`、`amount_band` 和 `decision_hash` 必须来自已验证的决策对象；自然语言 `reason` 只用于展示。

## 6. 工单数据模型

### 6.1 Case

```json
{
  "case_id": "case_01J...",
  "claim_id": "clm_01J...",
  "claim_version": 2,
  "decision_hash": "sha256:...",
  "approval_id": null,
  "type": "expense_review",
  "reason_code": "receipt_manual_verification",
  "reason": "凭证需要人工核验",
  "status": "queued",
  "priority": "normal",
  "queue_id": "finance_review",
  "assignee_id": null,
  "created_at": "2026-10-11T10:00:00Z",
  "due_at": "2026-10-12T10:00:00Z",
  "escalation_level": 0,
  "routing_rule_version": "expense-routing-v1",
  "source_request_id": "req_01J...",
  "idempotency_key": "handoff:clm_01J:2:receipt_manual_verification"
}
```

### 6.2 QueueDefinition

```json
{
  "queue_id": "finance_review",
  "display_name": "财务审核",
  "allowed_roles": ["finance_reviewer", "finance_admin"],
  "priority_order": ["urgent", "high", "normal", "low"],
  "response_sla_seconds": 14400,
  "resolution_sla_seconds": 86400,
  "escalate_to": "finance_admin"
}
```

队列配置属于受控配置，不能由 Agent 在请求参数中自由指定。没有匹配队列时进入 `unrouted` 并升级运营人员，不得默认分派给任意个人。

### 6.3 CaseEvent

事件至少包含：`event_id`、`case_id`、`event_type`、`from_status`、`to_status`、`actor_type`、`actor_id`、`queue_id`、`claim_version`、`request_id`、`created_at` 和结构化 `metadata`。

事件追加写入，不允许更新历史事件。通知、认领和 SLA 事件也必须进入同一审计流。

## 7. 工单状态机

```text
queued
  -> assigned
  -> cancelled
  -> escalated
  -> unrouted

assigned
  -> in_progress
  -> queued          # 释放认领或转入新队列后重新排队，并追加 transfer 事件
  -> escalated

in_progress
  -> resolved
  -> rejected
  -> needs_applicant
  -> escalated
  -> queued          # 暂停后回队列

needs_applicant
  -> queued          # 申请人补充材料
  -> cancelled

unrouted
  -> queued          # 责任队列恢复或路由规则补齐
  -> escalated
  -> cancelled

resolved / rejected / cancelled
  -> terminal
```

约束：

- `resolved` 只表示工单处理完成，不自动等同于 claim `approved`；
- 只有带有合法审批结果的 `resolved` 才能将 claim 更新为 `approved` 或 `rejected`；
- `escalated` 必须生成新的升级事件和目标队列，不能只修改展示字段；
- 终态工单不可重新认领或重复关闭；
- 所有转移必须检查操作者角色、当前版本和并发版本号。

## 8. 分派模型

### 8.1 分派输入

分派器只读取受信字段：`reason_code`、`category`、`amount_band`、`risk_level`、`applicant_org`、`required_role` 和政策版本。自然语言理由只能作为展示信息，不能单独决定权限队列。

### 8.2 分派顺序

```text
显式受控规则
  -> 费用类目/风险映射
  -> 申请人组织映射
  -> 队列可用性检查
  -> priority + due_at 计算
  -> 创建 queued case
```

分派规则必须版本化并记录 `routing_rule_version`。同一 claim 版本重复创建时，规则版本变化不能静默改写既有工单；应通过重新分派事件显式记录。

### 8.3 认领与转派

- 认领需要目标队列成员角色；使用乐观锁，已被其他人认领时返回 `case_already_claimed`；
- 认领超时只能释放处理锁，不得自动批准或关闭 claim；
- 转派必须填写 `reason`，写入原队列、新队列和操作者；
- Agent 只能请求“建议队列”，不能直接设置 `assignee_id`；
- 无可用队列时状态为 `unrouted`，并产生高优先级运营告警；无法在规定时间内恢复路由时再转为 `escalated`。

## 9. SLA 与升级

### 9.1 SLA 计时

工单创建时计算 `response_due_at` 和 `resolution_due_at`，使用队列配置和创建时的 SLA 版本。暂停、等待申请人和节假日规则在 MVP 中不改变已记录的原始截止时间；复杂日历另行立项。

### 9.2 升级规则

| 触发 | 动作 |
|------|------|
| 超过响应 SLA | 标记 `response_breached`，通知队列负责人 |
| 超过解决 SLA | 创建 `escalation` 事件，转入 `escalate_to` 队列 |
| 连续两次无人认领 | 提升优先级并转运营队列 |
| 工单处于 `needs_applicant` | 暂停业务处理，通知申请人补充材料 |
| 目标队列不可用 | 进入 `unrouted`，禁止静默丢弃 |

升级是系统动作，不是自动批准。每次升级必须幂等，重复扫描不能重复发事件或通知。

## 10. 通知适配器

### 10.1 MVP

先实现持久化通知 outbox，不直接依赖外部供应商：

- `case_created`：通知目标队列；
- `case_assigned`：通知认领人；
- `needs_applicant`：通知申请人；
- `sla_warning` / `sla_breached`：通知队列负责人；
- `case_resolved`：通知申请人和业务观察者。

通知发送失败必须保留 outbox 记录并支持重试；不能因为通知失败而改变审批结果。

### 10.2 外部适配器边界

邮件、IM 和企业审批平台只能通过显式 adapter 接入。每个 adapter 必须返回 `delivery_id`、状态和错误，不得把“调用成功”直接解释为“用户已阅读”。外部通知属于出站副作用，必须经过权限和网络策略。

## 11. HTTP 接口

沿用现有 Bearer 鉴权、`request_id`、结构化错误 envelope 和 `Idempotency-Key`。

Case 幂等键的规范作用域是 `handoff:<claim_id>:<claim_version>:<reason_code>`；同一 claim 版本和触发码必须复用活动 case。它不等同于 claim 写接口、决策子流程或审批决议的幂等键；跨作用域复用时必须重新生成对应键。

| 方法 | 路径 | 用途 |
|------|------|------|
| `POST` | `/v1/expense/cases` | 根据 claim 版本和 handoff 条件创建或复用工单 |
| `GET` | `/v1/expense/cases/{case_id}` | 查询工单、队列、SLA 和当前审批绑定 |
| `GET` | `/v1/expense/cases` | 按状态、队列、优先级和截止时间查询有权访问的工单 |
| `POST` | `/v1/expense/cases/{case_id}/claim` | 认领工单 |
| `POST` | `/v1/expense/cases/{case_id}/release` | 释放认领锁 |
| `POST` | `/v1/expense/cases/{case_id}/transfer` | 转派到受控目标队列 |
| `POST` | `/v1/expense/cases/{case_id}/resolve` | 提交人工处理结果并绑定审批决议 |
| `POST` | `/v1/expense/cases/{case_id}/escalate` | 升级到更高队列 |
| `GET` | `/v1/expense/cases/{case_id}/events` | 查询工单审计事件 |
| `GET` | `/v1/expense/queues` | 查询当前用户有权查看的队列摘要 |

创建请求示例：

```json
{
  "claim_id": "clm_01J...",
  "claim_version": 2,
  "reason_code": "receipt_manual_verification",
  "reason": "凭证需要人工核验",
  "suggested_queue": "finance_review"
}
```

`suggested_queue` 只作为规则输入，服务端必须重新校验，不接受 Agent 直接指定处理人。

`POST /v1/expense/cases/{case_id}/resolve` 的 `decision` 表示工单处理结果；当结果要求 claim `approved` 或 `rejected` 时，请求必须同时提供 `approval_id`、`claim_version`、`decision_hash` 和 `expected_case_version`，并由表单审批入口完成最终授权。没有合法 approval binding 时，case 只能结束为人工处理完成，不能改变 claim 终态。

## 12. 权限与数据安全

- 申请人只能查看自己的 claim、相关工单和申请人可见事件；
- 队列成员只能查看所属队列范围内的工单；管理员可以查看路由和审计，但不因管理员身份绕过审批版本校验；
- `claim` 核心字段和附件引用在工单创建后冻结；变更必须创建新版本并重新路由；
- `resolve` 必须绑定 `claim_version`、`decision_hash`、`expected_case_version`；
- 认领、转派、升级和关闭都是副作用操作，须经过权限闸门和角色校验；
- 未找到或无权访问的工单统一返回，不泄露其他组织的 `case_id` 存在性；
- 工单内容、通知 payload 和审计 metadata 必须脱敏，禁止保存密码、API key 或完整凭证内容。

## 13. 错误码

至少支持：

| 错误码 | 含义 |
|--------|------|
| `case_not_found` | 工单不存在或当前用户无权查看 |
| `case_already_exists` | 相同 claim 版本和触发指纹已有活动工单 |
| `idempotency_conflict` | 同一 case 幂等键对应不同 claim、版本或触发码 |
| `case_already_claimed` | 工单已被其他处理人认领 |
| `case_not_claimable` | 当前状态或角色不能认领 |
| `invalid_case_transition` | 状态转移不允许 |
| `queue_not_allowed` | 目标队列不在受控分派范围 |
| `queue_unavailable` | 目标队列暂不可用 |
| `unrouted_case` | 没有可匹配的责任队列 |
| `case_version_conflict` | 并发更新版本不一致 |
| `claim_version_mismatch` | 工单与 Expense claim 版本不一致 |
| `approval_binding_mismatch` | 审批记录与工单决策指纹不一致 |
| `sla_policy_unavailable` | 无法计算可靠 SLA，进入升级路径 |
| `notification_pending` | 业务状态已保存，通知进入 outbox 重试 |

## 14. 分阶段任务

### H0：契约和路由规则冻结

- 固定 reason code、队列定义、角色、状态机和错误码；
- 为每个 `human_handoff_conditions` 建立 reason code 映射；
- 固定 `routing_rule_version` 和 SLA 配置格式。

退出标准：非法状态、非法队列、重复触发和无匹配路由均有契约测试。

### H1：工单与审计存储

- 新增 case、queue、case event、outbox 数据模型；
- 使用 PostgreSQL 作为业务事实来源；
- 实现创建/查询/事件追加和幂等去重；
- 创建 case 时 `approval_id` 可以为空；case 需要改变 claim 批准结果时，必须绑定表单 SPEC 的合法 `approval_id`，不复制审批凭据逻辑。

退出标准：重启恢复、重复创建复用同一 case、事件不可篡改、越权查询失败。

### H2：分派、认领与升级

- 实现受控队列映射、认领锁、释放、转派和 escalation；
- 实现 SLA 截止时间和幂等扫描器；
- 加入无路由和队列不可用的失败关闭路径。

退出标准：并发认领只有一个成功；超时只升级不批准；转派有完整审计。

### H3：处理结果与审批衔接

- 实现 case resolve；
- 校验 claim 版本、decision hash 和审批角色；
- 将批准/拒绝结果通过表单 SPEC 的 `resolve_review` 回写 Expense Workflow；
- 仅复用 `/v1/approvals` 的过期、拒绝和一次性凭据语义；Expense 最终审批记录仍由表单 SPEC 的审批入口产生。

退出标准：无合法审批不能进入批准终态；版本替换、重复 resolve 和过期审批全部失败关闭。

### H4：通知与运营视图

- 实现 outbox worker 和重试策略；
- 增加队列摘要、待处理量、SLA breach 和人工接管率指标；
- 接入一个可替换的本地通知 adapter；
- UI 展示申请人的状态、审批意见和时间线。

退出标准：通知失败不丢业务事件；队列和 SLA 指标可由审计事件重建；UI 不将通知成功显示为审批成功。

## 15. 文件级实施清单

| 文件/目录 | 计划动作 |
|-----------|----------|
| `src/react_agent/apps/expense/handoff.py` | reason code、路由决策和工单状态转移 |
| `src/react_agent/apps/expense/case_store.py` | PostgreSQL case/queue/event/outbox 存储接口 |
| `src/react_agent/apps/expense/sla.py` | SLA 计算、扫描和升级事件 |
| `src/react_agent/server/fastapi_app.py` | 注册 `/v1/expense/cases` 和 `/v1/expense/queues` |
| `src/react_agent/safety/permissions.py` | 登记认领、转派、升级、resolve 和通知权限 |
| `src/react_agent/server/static/` | 队列/工单状态视图与 Expense 表单时间线 |
| `tests/` | 路由、幂等、并发认领、版本绑定、SLA、outbox 和越权测试 |
| `docs/operations/DEPLOY.md` | 增加存储、Worker、通知和 SLA 配置边界 |
| `docs/guide/PRODUCTION_MATURITY.md` | 分离本地工单原型证据与生产运营系统能力 |

## 16. 验收与发布边界

必测场景：

- 同一 claim 版本重复 handoff 只产生一个活动工单；
- Agent 建议队列不存在或无权限时不能直接指定个人；
- 两个处理人并发认领只有一个成功；
- claim 版本变化后旧工单 resolve 被拒绝；
- SLA 超时产生一次升级事件，不自动批准；
- 通知失败时业务事件和 outbox 均可恢复；
- 无合法审批绑定时工单不能把 claim 写成 `approved`；
- 申请人、队列成员和管理员看到的事件范围符合权限边界。

在 H4 完成并有独立验收证据前，对外只能描述为：

> Expense 支持结构化决策、人工审批状态和可审计的人工接管原型；内置工单分派、通知、SLA 和生产运营队列尚未完成。

不得使用“自动分派已上线”“已通知审批人”“SLA 已保障”或“自动报销已完成”等表述，除非对应外部系统和运行证据已经接入并验证。

## 17. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-10-11 | S0 契约统一：人工接管作为表单父 Workflow 的子流程；统一 escalated、approval 绑定、决策到 reason code 映射和 case 幂等键 |
