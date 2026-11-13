# Expense 人工接管、工单与队列分派规格

## 1. 文档状态

本文定义 `expense` 在表单与审批 Workflow 之后的人工接管扩展：当 Agent 或规则 Workflow 无法安全完成决策时，系统创建可追踪的人工工单，分派到有责任边界的队列，由人工认领、处理、升级并回写业务状态。

本文包含 H0–H4 存储能力与 S6 HTTP 接线。已接通受控 reason 自动建单和工单 HTTP 操作；这是可部署工程原型，不代表真实运营队列、邮件/IM 送达或生产 SLA。当前已有的 `approval_id`、待审批记录和人工决议接口仍是轻量审批基础设施；本规格在其上增加工单和运营闭环。

H0 契约实现为 `src/react_agent/apps/expense/handoff.py`，受控模拟配置为 `fixtures/expense/handoff_routing_v1.json`。H1–H4 复用 Claim SQL store，提供工单操作、审批绑定、本地通知重试与审计指标；`server/expense_cases.py` 接通 HTTP。执行进度统一见 [`roadmap-spec.md`](roadmap-spec.md)；各批历史证据保留，当前接线验收见 [S6 HTTP handoff](evidence/s6-http-handoff.md)。

相关规格：

- [`workflow-decision-spec.md`](workflow-decision-spec.md)：规则决策与决策节点；
- [`form-workflow-spec.md`](form-workflow-spec.md)：表单、claim 生命周期和审批接口。

本规格是表单父 Workflow 的后置人工接管子流程。`route_review` 只能把决策 SPEC 输出的结构化 `handoff` 转换为 case；它不得重新解释决策或直接改变 claim 终态。`case.resolve` 只完成工单处理，涉及 claim 批准/拒绝时必须调用并绑定表单 SPEC 的 `/v1/expense/reviews/{approval_id}/resolve` 记录。

## 2. 当前能力与缺口

当前项目可以：

- 通过 S4–S5 的同一 SQL store 保存 Claim/version/Decision、待审记录和人工决议；
- 由正式 Expense `route_review` / `resolve_review` 校验版本和指纹，保留审批与审计；
- 使用 H0 纯契约规划受控 reason、队列和路由/SLA 快照；
- 通过 H1 存储适配器创建独立 case ID、查询、追加证据事件并保存 pending outbox；H1 SQLite/PostgreSQL 合同及实际数据库重启恢复已验证；
- 通过 H2 存储方法自认领、释放、转派、升级、计算冻结截止时间和按页扫描；H2 的验证单独记录，不沿用 H1 的 PostgreSQL 通过结论；
- H3 在同一事务中经既有 `resolve_review` 回写 Claim，并提供显式等待补料/恢复存储方法，当前验收见 H3 独立证据。
- H4 提供有界本地 outbox worker、重试回执和可由审计重建的指标；无常驻调度；
- S6 将工单创建、查询、认领、释放、转派、升级、开始、补料等待/恢复和 resolve 接入 HTTP；正式 Claim HTTP store 的 `submit` / `route_review` 在同一事务为受控 reason 建单。

通用 `/v1/approvals` 继续只是 CONFIRM 凭据兼容口，不替代正式 Expense 审批。H1 不写 Claim 或审批，不提供新的批准入口。

当前项目尚不能：

- 将旧 S5 自由文本 reason 自动转换为受控 reason；旧路径明确 blocked，不重写 Decision 指纹；
- 根据业务类型、组织或金额进行多维自动分派；v1 只按受控 reason 精确匹配；
- 提供通用 Agent 人工接管或 S7 队列/审批台界面（独立申请人表单见 [S7 第一刀](evidence/s7-claim-form.md)）；
- 发送站内、邮件或消息通知；
- 提供定时 SLA 调度器、真实超时通知或生产 SLA 保障；
- 自动恢复等待补料的业务处理；必须由申请人显式 resume，然后重新认领。

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

### 5.3 H0 受控 reason 与条件映射

| 条件标识（精确匹配） | `reason_code` | v1 责任队列 / 优先级 |
|---|---|---|
| `规则未覆盖费用类型` | `policy_not_covered` | `finance_review` / normal |
| `金额或凭证需要人工核验` | `receipt_manual_verification` | `finance_review` / normal |
| `需要持久化审批结果` | `approval_record_required` | `finance_review` / normal |
| `policy_conflict` | `policy_conflict` | `finance_admin` / high |
| `policy_version_unknown` | `policy_version_unknown` | `expense_operations` / high |
| `automation_limit_exceeded` | `automation_limit_exceeded` | `finance_admin` / high |
| `appeal_requested` | `appeal_requested` | `finance_review` / normal |
| `escalation_requested` | `escalation_requested` | `finance_admin` / high |
| `dependency_unavailable` | `dependency_unavailable` | `expense_operations` / high |

前三项覆盖当前 Expense Skill 的全部 `human_handoff_conditions`；后六项是 §5.1 触发类型的结构化预留标识，不声称当前 Agent 已产生这些事件。未知条件返回 `unknown_handoff_condition`，不做关键词猜测。`receipt_manual_verification` 在 v1 中同时表示金额或凭证事实需核验；明确超出自动阈值则使用 `automation_limit_exceeded`。

条件映射只是词表，不能单独授权建单。`plan_handoff` 只接收经 `Decision` 校验且绑定 Claim/version/policy/hash 的对象；必须有 `review_required`、`not_covered`、`needs_review` 或 `escalated` 才规划工单。普通正向建议、无需例外的硬拒绝，即使携带 `approval_record_required`，也不创建计划。`handoff.reason_code` 不在受控集合或绑定不全时返回 `invalid_handoff`，不从自由文本补造。现有 S5 的兼容 handoff reason 不在本轮改写；未来接入时须由可信决策适配层显式映射，不允许请求方重写已验证指纹。

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
  "case_version": 1,
  "lock_expires_at": null,
  "created_at": "2026-10-11T10:00:00Z",
  "response_due_at": "2026-10-11T14:00:00Z",
  "resolution_due_at": "2026-10-12T10:00:00Z",
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
  "sla": {
    "sla_policy_version": "expense-sla-v1",
    "response_sla_seconds": 14400,
    "resolution_sla_seconds": 86400
  },
  "escalate_to": "finance_admin",
  "available": true
}
```

队列配置属于受控配置，不能由 Agent 在请求参数中自由指定。没有匹配队列时进入 `unrouted` 并升级运营人员，不得默认分派给任意个人。

H0 固定以下队列及处理角色，`escalate_to` 是队列 ID，不是个人或角色 ID。身份认证、组织成员关系和动作授权在 H2/H3 接通；此处角色校验仅定义队列准入，不提供身份凭据，也不授予 Claim 审批权。

| 队列 | 处理角色 `allowed_roles` | 升级目标 |
|---|---|---|
| `finance_review` | `finance_reviewer`、`finance_admin` | `finance_admin` |
| `finance_admin` | `finance_admin` | `expense_operations` |
| `expense_operations` | `expense_operator` | `finance_admin` |

`applicant` 只代表申请人，不是处理角色；读取范围仍按 §12。未知队列、未定义的规则/升级目标、未知角色或不属于队列的处理角色返回 `queue_not_allowed`。队列不可用返回 `queue_unavailable`，不得绕过准入换一个人。优先级顺序固定为 `urgent, high, normal, low`。

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

escalated
  -> queued          # 明确目标队列后重新排队，再按权限认领
  -> unrouted        # 升级目标不可用
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

H0 的 `validate_transition` 只校验上列静态边，未知状态、自转移和所有未列出的边均返回 `invalid_case_transition`。`escalated` 不能直接 `resolved/rejected`；需先回队列、认领并进入处理。角色、并发锁和审批绑定是 H2/H3 的执行约束，静态校验成功不能替代它们。

## 8. 分派模型

### 8.1 分派输入

分派器只读取受信字段：`reason_code`、`category`、`amount_band`、`risk_level`、`applicant_org`、`required_role` 和政策版本。自然语言理由只能作为展示信息，不能单独决定权限队列。

### 8.2 分派顺序

```text
显式受控规则
  -> 费用类目/风险映射
  -> 申请人组织映射
  -> 队列可用性检查
  -> priority + response_due_at / resolution_due_at 计算
  -> 创建 queued case
```

分派规则必须版本化并记录 `routing_rule_version`。同一 claim 版本重复创建时，规则版本变化不能静默改写既有工单；应通过重新分派事件显式记录。

H0 v1 配置顶层固定为 `routing_rule_version`、`queues`、`rules`，示例版本为 `expense-routing-v1`；规则项为 `{reason_code, queue_id, priority}`，每个 reason 最多一条。`queues` 使用 §6.2 的格式，完整配置见 fixture。缺失或空版本、重复规则/队列及格式错误失败关闭。v1 只按受控 reason 精确匹配，不实现类目、组织、金额或风险多维路由；这些字段继续来自已验证 Decision，不接受自然语言选人。

`plan_handoff` 只返回 `HandoffPlan`：Claim/version/hash、reason/risk/amount、状态、队列、优先级、路由版本及 SLA 快照。无匹配返回 `unrouted/unrouted_case`；目标队列不可用返回 `unrouted/queue_unavailable`；两者 queue/SLA 均为空、优先级 high，不尝试默认分派。H0 不生成告警、截止时间或 case ID，运营升级与重新分派留给 H2。

### 8.3 认领与转派

- 认领需要目标队列成员角色；使用乐观锁，已被其他人认领时返回 `case_already_claimed`；
- 认领超时只能释放处理锁，不得自动批准或关闭 claim；
- 转派必须填写 `reason`，写入原队列、新队列和操作者；
- Agent 只能请求“建议队列”，不能直接设置 `assignee_id`；
- 无可用队列时状态为 `unrouted`，并产生高优先级运营告警；无法在规定时间内恢复路由时再转为 `escalated`。

## 9. SLA 与升级

### 9.1 SLA 计时

工单创建时计算 `response_due_at` 和 `resolution_due_at`，使用队列配置和创建时的 SLA 版本。暂停、等待申请人和节假日规则在 MVP 中不改变已记录的原始截止时间；复杂日历另行立项。

H0 冻结 `sla` 对象为 `sla_policy_version`（非空字符串）、`response_sla_seconds` 和 `resolution_sla_seconds`（正整数，拒绝布尔值/字符串，且 response ≤ resolution）。单位为自然经过的秒，示例 `expense-sla-v1` 是模拟配置，不是生产 SLA 承诺。配置无法校验则返回 `sla_policy_unavailable` 并停止规划；实际截止时间计算、超时扫描与升级在 H2 实现。新计划只保存配置快照；规则或 SLA 版本变化不改写已有快照。

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

H0 用显式传入的既有 case 路由快照验证复用契约：相同作用域且 hash 相同返回原快照及 `case_id`，保留原路由/SLA 版本；任何 Claim、版本、reason 或 hash 不同返回 `idempotency_conflict`。同作用域终态 case 返回 `case_already_exists`，不因重放重新打开；新申请需新 Claim 版本。该纯函数不查询数据库，H1 必须用事务/唯一约束保证实际并发去重，不能把 H0 测试当成持久化或并发证据。以下 HTTP 接口仍为规划。

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
| `POST` | `/v1/expense/cases/{case_id}/start` | 认领人显式开始处理 |
| `POST` | `/v1/expense/cases/{case_id}/needs_applicant` | 请求补料并释放处理锁 |
| `POST` | `/v1/expense/cases/{case_id}/resume` | 申请人显式补料回 queued，不重跑业务 |
| `GET` | `/v1/expense/cases/{case_id}/events` | 查询工单审计事件 |
| `GET` | `/v1/expense/queues` | 查询当前用户有权查看的队列摘要 |

创建请求示例：

```json
{
  "claim_id": "clm_01J...",
  "claim_version": 2,
  "decision_hash": "sha256:<persisted-decision-hash>",
  "reason_code": "receipt_manual_verification",
  "reason": "凭证需要人工核验",
  "suggested_queue": "finance_review"
}
```

`suggested_queue` 只作为规则输入，服务端必须重新校验，不接受 Agent 直接指定处理人。

### 11.1 S6 已实现的 HTTP 契约

这些路由共享 Claim 的服务级 Bearer 鉴权和 `X-Actor-Id` 原型业务身份。Bearer 是否启用沿用现有服务配置（`REACT_AGENT_AUTH_TOKEN`）；它不是用户身份 token。部署者必须在可信调用边界提供 actor ID，不声称生产级身份或多租户系统。

- 服务端从 `REACT_AGENT_EXPENSE_CASE_ACTORS_FILE` 指定的受信 JSON 文件构造 `CaseActor`，文件为 `{actor_id: {role, queue_ids}}`。示例：`{"finance-demo": {"role": "finance_reviewer", "queue_ids": ["finance_review"]}}`。未登记者只获 applicant；未配置目录不授予处理权限；格式/读取失败返回 `identity_unavailable`。客户端 JSON 的 role、queue_ids、assignee_id 等额外字段拒绝，相关 header 不参与授权。成员与队列角色须同时匹配，认领人固定为当前 actor。
- 路由配置来自受信 `REACT_AGENT_EXPENSE_CASE_ROUTING_FILE`，默认现有 `fixtures/expense/handoff_routing_v1.json`，在 HTTP store 初始化时读取。v1 不使用客户端 suggested_queue 改变队列；reason_code 若提供必须等于持久化 Decision 的受控值。角色目录每请求读取；两文件均为服务器配置，不能由请求指定。
- 写请求必须有 `Idempotency-Key`；创建按 Claim/version/reason 原子去重，同键不同 payload 冲突。活动工单返回原 case，不重算路由/SLA；终态不重开。创建时省略 approval_id 自动绑定该版本已有 pending 审批，显式 null 保留 H1 无审批建单能力；之后批准/拒绝仍只能绑定合法既有审批。
- 创建必填 claim_id、claim_version、decision_hash；action 必填 expected_case_version。release/transfer/escalate/needs_applicant/resume 必填非空 reason，transfer 可指定受控 target_queue_id，resume 另需 claim_version、decision_hash、evidence_ref。resolve 的 approval_id 必须显式提供（纯工单 complete 时可为 null），另需 decision、claim_version、decision_hash、expected_case_version、reason。通过已有权限闸门，`X-Approval-Credential` 只满足共享 CONFIRM，不替代 Expense 审批。
- `/queues` 仅返回当前角色/成员可见队列及审计重建摘要；applicant 返回空队列列表。工单列表只返回有权可见的工单。单条读取/操作的不存在和越权统一返回 404 `case_not_found`，不通过角色/审批错误泄露单据存在。
- HTTP store 初始化时启用受信 `enable_handoff(routing)`；其他可信应用若复用 SQL `submit` / `route_review`，使用同一显式接线。受控 handoff 的 case/event/outbox 与提交/待审同事务提交或回滚，无路由/不可用队列持久化 unrouted。旧 S5 自由文本 reason 返回 `handoff={status: blocked, error_code: invalid_handoff}`，不建单、不改变其 Decision 指纹和现有 S5 审批语义。
- 本轮不暴露 outbox worker、SLA scan 的维护 HTTP，也不启动后台常驻调度；仍用已有有界可信应用调用。`resolve_review` 保留正式审批事实来源，case.resolve 只组合现有入口。

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
| `case_already_exists` | 同作用域已有工单且无法复用，例如终态重放；活动工单正常复用返回原 case |
| `idempotency_conflict` | 同一 case 幂等键或复用快照对应不同 claim、版本、触发码或 decision hash |
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
| `invalid_handoff` | Decision 或既有 case 快照无效、缺少绑定或 reason 不受控 |
| `invalid_routing_config` | 路由配置格式、版本或规则唯一性不合法 |
| `unknown_handoff_condition` | 条件未在精确映射表中注册 |

H0 只冻结完整错误词表，并使用契约校验相关错误；`notification_pending`、认领/并发/审批错误等不表示相应运行能力已实现。

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

#### H1 存储接口与验收边界

`ExpenseCaseStore(ExpenseClaimStore(...))` 复用正式 Claim 的 SQLAlchemy engine、metadata 和数据库 URL，不维护另一套审批库。持久化表为 `expense_cases`、`expense_case_events`、`expense_case_outbox`；queue definition 作为建单时的不可变配置快照存入 case，暂不建立可变队列目录。

- `create` 只读取已保存且通过 `Decision` 校验的 Claim/version/hash/handoff，受控路由由服务端提供；不接受自由指定的 reason、队列、处理人或客户端 Decision。申请人限本人，受信财务管理员可建单。
- PostgreSQL 事务与 Claim 行锁、`(claim_id, claim_version, reason_code)` 唯一约束保证建单去重，case、首事件和 outbox 同时提交或回滚。活动工单重放返回同一 case，保留创建时路由/SLA；hash/approval 绑定冲突拒绝，终态不重开。SQLite 仅用于契约测试，写操作使用 `BEGIN IMMEDIATE`。
- `get` / `list_cases` / `events` 按申请人归属或受信处理角色与队列成员关系控制读取；不存在与无权限统一 `case_not_found`。`CaseActor` 是可信调用方提供的身份上下文，不是身份认证，不允许直接信任客户端角色或队列 header。财务管理员的审计访问不授予批准权。
- `append_event` 仅追加 `evidence_recorded` 和不透明凭证引用，不接受任意状态事件或完整凭证正文；调用方负责引用脱敏。case 行锁、事件键和序号唯一约束保证并发追加有序、重放不重复。事件的数据库 trigger 拒绝 UPDATE/DELETE，PostgreSQL 也拒绝 TRUNCATE；不声称能防止数据库管理员删除 schema 或禁用触发器。
- `approval_id` 可以为空；非空时必须指向已有且 Claim/version/hash 一致的 Expense 审批。H1 不绑定或执行新的审批、不修改 Claim；H3 改批准结果时仍必须经过既有 `resolve_review` 与权限闸门。
- `outbox` 仅供有权处理者读取 pending 意图，不发送、不标记已送达、不做重试 Worker。无路由时保存运营通知意图，case 仍为 `unrouted`，不默认分派。

当前 S5 的兼容自由文本 handoff reason 不在本轮改写。H1 对它们失败关闭；可信决策适配、HTTP 和自动建单尚未接入，不把合成结构化 Decision 的存储测试描述为完整业务链路。H2 的存储操作边界见下文；H3 的独立存储方法见下文；HTTP/自动建单、H4 通知与界面继续后置。

### H2：分派、认领与升级

- 实现受控队列映射、认领锁、释放、转派和 escalation；
- 实现 SLA 截止时间和幂等扫描器；
- 加入无路由和队列不可用的失败关闭路径。

退出标准：并发认领只有一个成功；超时只升级不批准；转派有完整审计。

#### H2 存储方法与时间语义

`ExpenseCaseStore` 提供 `claim_case`、`release_case`、`transfer_case`、`escalate_case` 和 `scan_sla`。身份、角色、队列成员关系及 `RoutingConfig` 必须由可信调用方提供；本轮没有 HTTP/Agent 工具入口或客户端身份认证。财务管理员的全局审计读取权限不授予跨队列认领权。任何方法都不写 Claim、审批记录或批准终态。

- 新增 `expense_case_work` 保存可变处理状态，`expense_case_actions` 保存动作幂等结果；H1 三张表和创建快照保留。新表可追加创建，既有 H1 case 的读操作从创建快照计算默认状态，首次变更在事务内初始化；不重写历史事件。
- 每次写操作传 `expected_case_version`、`request_id`、`idempotency_key`；PostgreSQL 按 Claim→case 顺序加行锁，SQLite 只用于合同测试并以 `BEGIN IMMEDIATE` 串行写入。case 版本、事件、动作幂等结果和可选 pending outbox 原子提交。版本冲突无写入；同一 case/key 的同一身份与请求返回原结果，换 payload 返回 `idempotency_conflict`，换身份隐藏为 `case_not_found`。转派重放仍校验原队列成员权限。
- `claim_case` 仅从 queued 自认领，处理角色和目标队列成员关系须同时满足，且复核当前受控队列可用性。接口不接收 `assignee_id`；已有其他人的有效锁时优先返回 `case_already_claimed`。默认锁期 900 秒，可由可信构造参数设置为 1–86400 秒。首认领记录 `responded_at`。
- `release_case` 仅由原认领人执行并提供原因；到期锁也可由扫描或下一次合法操作释放。锁过期只写 `claim_lock_expired`、清除处理人并回 queued，不自动转派、关闭或批准。不存在背景定时器，调用方须显式执行扫描；时钟仅用于可复现测试，实际使用 UTC。
- 转派必须有非空原因；目标是受控队列 ID 或当前受控 reason 规则的结果。审计记录操作者、原/新队列、原/新处理人、锁期限、case 版本和路由版本。转派清锁并回 queued；升级按当前队列快照的 `escalate_to` 进入 escalated。queued→queued 的跨队列转派、escalated→escalated 的跨队列升级是带审计的路由变化，不开放通用状态自转移；H0 静态校验器保持不变。escalated 须显式回 queued 后才能认领。
- 无匹配或不可用队列进入 `unrouted`，清锁、保留错误码并追加高优先级运营 pending outbox 意图，不默认指定个人；assigned/in_progress 经合法 escalated 边再进入 unrouted。恢复路由必须显式转派，扫描不静默改写已有路由。
- 建单时按创建 SLA 快照计算 `response_due_at`、`resolution_due_at`，转派或配置升级不延长截止时间。原来 unrouted 且无 SLA 的 case 在首次成功路由时冻结 SLA，仍以原始 `created_at` 计时；日期溢出以 `sla_policy_unavailable` 回滚。
- `scan_sla` 仅供受信财务管理员维护调用；每页 1–1000 项、按 case ID 游标翻页、每 case 独立事务。响应超时仅记录一次 `sla_response_breached` 与 pending 提醒；认领晚于响应截止仍记违约。解决超时仅触发一次受控队列升级及 `sla_resolution_breached`；同时超时各有一个违约事件、仅一次队列升级。持久标记和事件同事务，重复/并发扫描均不重复升级或通知意图。
- 扫描遇到 Claim 版本漂移返回冲突，不写旧 case；终态跳过。`needs_applicant` 的恢复由 H3 定义，本轮扫描报告 `invalid_case_transition`，不自动恢复业务处理。§9.2“连续两次无人认领”的轮次/重置时钟尚未冻结，本切片不另加循环计时器，也不以两次处理锁到期代替该规则。

H2 是可部署原型的存储能力，不代表自动建单、定时调度、通知送达或生产 SLA。H3 的独立存储方法见下文；HTTP/自动建单、H4 通知发送、S7 UI、交付线和 Go 重写均未接入。

### H3：处理结果与审批衔接

- 实现 case resolve；
- 校验 claim 版本、decision hash 和审批角色；
- 将批准/拒绝结果通过表单 SPEC 的 `resolve_review` 回写 Expense Workflow；
- 仅复用 `/v1/approvals` 的过期、拒绝和一次性凭据语义；Expense 最终审批记录仍由表单 SPEC 的审批入口产生。

退出标准：无合法审批不能进入批准终态；版本替换、重复 resolve 和过期审批全部失败关闭。

#### H3 存储契约与审批边界

本切片提供 `start_case`、`request_applicant`、`resume_case`、`resolve_case`，仅由可信应用调用，不接 HTTP 或 `route_review` 自动建单。`CaseActor` 仍只是可信身份上下文，不提供生产认证或多租户身份系统。

- 处理人先自认领，再以 `start_case` 从 assigned 进入 in_progress。开始、等待、结案均要求队列成员与处理角色、本人有效处理锁和 `expected_case_version`；过期锁拒绝操作，由既有释放/扫描路径解锁，不在失败请求中写状态。
- `resolve_case` 必传 `approval_id`（可为 null）、`claim_version`、`decision_hash`、`expected_case_version`、`request_id`、`idempotency_key`、非空 `reason` 及 `decision`。`decision` 仅为 `approve/reject/complete`，不是任意 case 状态或 Claim 状态。
- approve/reject 仅供当前队列的 finance_reviewer/finance_admin 处理人。审批 ID 必须是既有 pending Expense review，匹配 case 与当前 Claim/version/持久化 Decision hash；创建时未绑定的 case 可在结案时绑定已有合法审批，已绑定的 case 不可替换绑定。不会自动创建新审批。`expense_operator` 可完成人工作业，不能批准/拒绝 Claim。
- 批准/拒绝调用现有 `resolve_review` 权限入口，通过连接适配器复用 S5 的原审批写入逻辑。PostgreSQL 统一 Claim→case→review 锁顺序，Claim、原审批决议、Claim 审计、case 绑定/版本/结案审计和动作记录同一事务提交；任一 SQL 写入失败全部回滚，不维护第二套批准记录。
- async 权限模式下，H3 要求一次性 CONFIRM 凭据精确绑定 tool、case ID/版本、Claim/version/hash、审批 ID、决议、处理人及意见；不使用工具级 session grant。过期、deny、已消费、绑定不匹配或 session 凭据均拒绝。一次性凭据消费补上批准后的 expires_at 检查。既有 HITL、显式开发 auto_allow/关闭闸门仍遵循原配置，不能将其测试描述为人工授权证据。
- CONFIRM 文件凭据与 SQL 不是分布式事务：SQL 失败仍保留凭据已消费，业务记录全部回滚，重试需重新人工批准新的凭据；绝不恢复一次性凭据。Expense approval_id 与 CONFIRM credential ID 是两个不同标识。
- `complete` 只完成人工作业，经 `case.resolve` 权限闸门后进入 case resolved，保留现有可空审批绑定，不修改 Claim 或 Expense 审批。approve/reject 成功后 case 也为 resolved，分别由原审批把 Claim 写成 approved/rejected；case resolved 不代表付款。
- 所有 resolve 重复调用均失败关闭，包括相同幂等键；不会复用 S5 的成功结果重复关单。终态不可再次 resolve；旧 case 版本、Claim 版本替换或 Decision 指纹变化无业务写入。审计包含原/现审批绑定、Claim 前后状态、实际决议、操作者和 case 版本。

#### needs_applicant 的显式恢复

`request_applicant` 只允许 in_progress→needs_applicant，必须记录原因并清除处理锁；业务处理暂停。等待期间截止时间和违约标记保持原快照，不暂停/重算 SLA。

只有原申请人可通过 `resume_case` 提交不透明 `evidence_ref` 与原因，绑定原 Claim/version/hash 和当前 case 版本，显式 needs_applicant→queued；这是补充核验材料引用，不改变 Claim 核心字段或附件。核心内容变化仍需新 Claim 版本并重新路由，旧 case 拒绝恢复。重复相同补料动作返回原结果，不追加事件。目标队列缺失/不可用则同一事务进入 unrouted 并保留运营 pending 意图。

恢复只重新排队，之后必须重新认领、开始处理和显式结案；不运行决策 Workflow、不修改 Claim 业务状态、不自动审批。转派、认领、扫描、关单均不能把 needs_applicant 隐式恢复；扫描继续报告 invalid_case_transition，不写等待工单。已过期的 SLA 在显式恢复后才由下一次显式扫描按原有规则处理。

H3 验收见 [H3 验证记录](evidence/h3-case-resolution.md)，限定 H4 见下文与 [H4 验证记录](evidence/h4-local-notifications.md)。S6 仍为 in_progress，HTTP/自动建单和界面未接入，不宣称生产 SLA。

### H4：通知与运营视图

- 本轮限定为持久化 outbox worker、重试、可替换的本地通知 adapter，以及可从审计重建的指标；HTTP、自动建单、真实邮件/IM 和 S7 UI 不在范围内。
- 原始 pending 意图保留不改写；新增投递状态表管理 processing lease、attempt、retry_wait / accepted。每次领取、过期恢复和结果追加到不可变 case event；领取和结果分别提交，adapter 调用不持有业务事务。仅受信 finance_admin 可运行 worker 和导出全局指标审计。
- 重试采用有上限的指数退避时间、不自动丢弃意图；崩溃后的租约到期可重领。outbox_id 是稳定 adapter 幂等键。数据库结果提交前崩溃可能重复调用，语义为至少一次；本地 adapter 用唯一键保存持久化本地回执并去重，不声称跨外部系统恰好一次。
- adapter 必须返回 delivery_id（失败时可空）、accepted / failed 状态与机器错误码。accepted 只表示本地 adapter 接受，不表示用户已读、真实通知、审批成功或 SLA 保障。异常只保存脱敏错误码，不保存异常正文。
- 复用 case_created、case_claimed→case_assigned、case_needs_applicant→needs_applicant、sla_*_warning→sla_warning、sla_*_breached→sla_breached、case_resolved 意图；既有转派/升级/unrouted 意图继续保留。收件目标绑定来源事件：队列、认领人、申请人，结案同时包含业务观察队列；不读取当前认领人替换历史收件目标。
- scan_sla 可显式设置 warning_before_seconds（默认 0，关闭提前提醒），只在截止前窗口记录每类一次 warning 与意图；重复扫描不重复。截止时间、审批和 needs_applicant 恢复规则不变。
- 指标只读审计事件：队列按最新业务事件归属，待处理量为非终态 case 数（含 needs_applicant / unrouted），SLA breach 为已扫描记录的 distinct case/类型，不能推断尚未扫描的超时。人工接管率分子为有 case_created 的 distinct Claim/version，分母为有 claim_submitted 的 distinct Claim/version；多个 reason 不重复计数。旧审计缺少 Claim 关联或分子缺失提交证据时返回 unavailable，不猜测成功率。通知审计不改业务指标。

退出标准：通知失败/重试/崩溃恢复不丢业务事件、不改审批；并发领取与稳定幂等键可验证；队列、SLA 和人工接管率可由导出的审计重建。该限定切片不代表整个 S6 或 UI 完成。

本地调用入口（可信应用调用，不接受客户端自报角色）：

```python
from react_agent.apps.expense.notifications import LocalNotificationAdapter, OutboxWorker

# cases 为既有 ExpenseCaseStore；maintenance_actor 来自可信身份上下文。
worker = OutboxWorker(cases, LocalNotificationAdapter(cases), actor=maintenance_actor)
worker.run_once(limit=100)  # 有界调用；无自动调度、HTTP 或外部网络通知。
audit = cases.metrics_audit(actor=maintenance_actor)
metrics = cases.metrics(actor=maintenance_actor)
# rebuild_metrics(audit) 可独立离线重建同一指标，无需查询 case/work/decision 表。
```

`outbox()` 返回原始 pending 意图；`delivery_status()` 单独返回投递进度。新增两张 H4 表可附加到现有 H1–H3 schema，不删除旧意图。已有 pending 意图可被消费，历史上未建 outbox 的动作不回填、不改写旧审计。失败无限保留供重试，退避默认 5 秒起、最长 3600 秒；没有后台常驻调度、保留期限或生产吞吐承诺。租约与时间依赖调用方受信时钟，adapter 应有有限执行时间，租约过期的旧结果不能覆盖新结果。

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

当前 S6 的对外描述为：

> 企业内部工作助手的报销场景支持受控 reason 自动建单、HTTP 认领/升级和绑定已有审批的人工处理；可重试本地通知回执与审计指标提供工程验证。旧自由文本 reason 仍 blocked；真实邮件/IM、常驻调度、界面和生产运营保障尚未接入。

不得使用“自动分派已上线”“已通知审批人”“SLA 已保障”或“自动报销已完成”等表述，除非对应外部系统和运行证据已经接入并验证。

## 17. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-10-11 | S0 契约统一：人工接管作为表单父 Workflow 的子流程；统一 escalated、approval 绑定、决策到 reason code 映射和 case 幂等键 |
