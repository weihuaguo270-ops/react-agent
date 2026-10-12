# Expense 跨 SPEC 实施总控规格

## 1. 文档职责

本文统一 `expense` 业务跨规格的实施顺序、依赖、阶段状态和退出门槛。S0–S8 是项目级执行序列，横跨多份业务规格；它们不是任一单独 SPEC 的内部批次编号。

本文只作为执行编排和进度索引，不复制领域规则、API 字段或状态机定义。领域语义发生冲突时，由下列来源规格负责定义；本文负责指出在哪个 S 阶段落实并验证这些语义。

| 来源文档 | 权威范围 |
|---|---|
| [`EXPENSE_POLICY_BOUNDARY_SPEC.md`](EXPENSE_POLICY_BOUNDARY_SPEC.md) | 规则依据、规则优先级、政策边界和当前实现差距 |
| [`EXPENSE_WORKFLOW_DECISION_SPEC.md`](EXPENSE_WORKFLOW_DECISION_SPEC.md) | 决策契约、规则决策模型、`expense_claim_review@1` 决策 Workflow、决策评测 |
| [`EXPENSE_FORM_WORKFLOW_SPEC.md`](EXPENSE_FORM_WORKFLOW_SPEC.md) | Claim 表单 schema/lifecycle、正式审批入口、审批和持久化语义 |
| [`EXPENSE_HUMAN_HANDOFF_SPEC.md`](EXPENSE_HUMAN_HANDOFF_SPEC.md) | handoff reason、case、队列、认领、SLA 和人工处理流程 |

冲突裁决原则：政策含义以 Policy Boundary 和确认后的政策 fixture 为准；正式 Claim 状态与审批授权以 Form Workflow Spec 为准；决策对象及决策执行以 Decision Spec 为准；case 运营流程以 Human Handoff Spec 为准。总控文档不得覆盖这些定义。

## 2. 当前进度

状态按可检查的代码、测试和报告记录，不以计划文字推断完成。

| 阶段 | 状态 | 当前证据或未完成项 |
|---|---|---|
| S0 规格裁决 | complete | 政策边界和主要冲突已在来源规格中裁定；待确认项已转为明确模拟规则或显式延期项 |
| S1 基线冻结 | complete | [`S1_BASELINE_2026-10-12.md`](../evaluation/expense/S1_BASELINE_2026-10-12.md)：legacy 8 案、Expense 定向测试及 HTTP smoke；demo 环境阻塞如实记录 |
| S2 共享领域契约 | complete | `domain.py`、legacy adapter、契约测试和 candidate runner 已实现；报告在 `artifacts/expense/candidate-s2-20261012/` |
| S3 决策 Workflow | not_started | 尚未实现 `expense_claim_review@1`；candidate dev 中 2 个采购证据 known gap，须在本阶段由可信模拟 registry 路径关闭或转入受控 review |
| S4 Claim 持久化 | not_started | PostgreSQL Claim/version/audit store 与草稿、提交、冻结、查询未实现 |
| S5 审批闭环 | not_started | Expense 审批 API、`route_review` / `resolve_review`、权限和过期/重放保护未实现 |
| S6 人工接管 | not_started | H0–H3 case/event/outbox、分派、认领/SLA、resolve 与 approval 绑定未实现 |
| S7 表单 UI 与运营视图 | not_started | 独立表单主路径、待审列表和 case 时间线未实现 |
| S8 验收与可选模型 | not_started | 全链路验收尚未执行；JEV 类模型保持可选，且只能在规则/Workflow/审批门禁后评估 |

S2 candidate 结果：dev 41 案 39 通过、2 个采购验证 known gap（故 dev 命令为非零）；golden 12/12；held_out 16/16。held_out manifest hash 为 `f8801e86298c59260b8d510df9c965f953bcbc5430672fefdbb50b523457da36`。这些是离线候选规则/契约结果，不代表 Workflow、数据库、审批、人工作业或生产能力。

## 3. 跨 SPEC 执行序列

每个阶段须通过自己的退出门槛后，才将状态更新为 complete。后续阶段可定义尚未实现的依赖，但不能把设计或 fixture 描述计为实现证据。

| 阶段 | 工作范围与交付 | 权威来源 | 依赖 | 退出门槛 | 状态 |
|---|---|---|---|---|---|
| S0：规格裁决 | 裁决规则优先级、`escalated` 非终态语义、Claim/Decision schema、审批入口、错误码、幂等边界；将未有依据的行为显式延期 | Policy Boundary §5；Decision §5–6；Form §5–11；Handoff §5–13 | 无 | 三份实施 SPEC 与政策边界不存在相互矛盾的对外语义；未决项有 owner/延期边界 | complete |
| S1：基线冻结 | 固定 legacy 决策、`ExpenseLedger`、`/v1/chat`、`expense_claim_review` 及旧 dev/golden/held_out 结果 | Decision §4、§8、§10；baseline report | S0 | 有可追溯报告、命令、fixture/代码版本、失败和环境限制；不覆盖后续历史 | complete |
| S2：共享领域契约 | 统一 Claim/version、Decision、ApprovalRecord、AuditEvent、Handoff reason、decision hash、错误码；保留 legacy adapter；实现扩展候选 fixture runner 和 held_out hash 保护 | Decision §6、§8、§10；Form §5、§11、§12 P0；Coverage Matrix | S0、S1 | 契约测试通过；旧入口回归；候选 runner 可执行并区分 pass/known_gap/fail；held_out hash 固定 | complete |
| S3：决策 Workflow | 将 `decide()` 包装为 `expense_claim_review@1`；实现固定节点、失败关闭、轨迹、决策审计适配和幂等重放；对采购/报价证据使用 Workflow 控制的模拟 adapter，不信任客户端自报验证结果 | Decision §5、§6、§10 P2；Policy Boundary 决策规则；Coverage Matrix `W-ADAPTER-*` | S2 | 节点注册/顺序/成功跳过失败轨迹可断言；规则输出与 S1 逐案兼容；未知或不可验证证据不得自动批准；`W-ADAPTER-*` 有测试 | not_started |
| S4：持久化 Claim 生命周期 | 建 PostgreSQL Claim/version/audit store；实现 draft create/read/update、submit、版本冻结、状态迁移和查询；Ledger 留作 legacy/eval adapter | Form §5–9、§11、§12 P1；Decision §6.3 | S3 | 重启后数据可查询；提交冻结版本；重复请求幂等；版本冲突无副作用；审计完整 | not_started |
| S5：审批闭环 | 统一 Expense approval API；实现 `route_review` / `resolve_review`、CONFIRM 权限、Claim version/decision hash 校验、过期/拒绝/重复使用保护；只有合法审批可改变 Claim 状态 | Form §4–8、§11、§12 P2；Decision §6.3 | S4 | approve/reject/escalate、无效凭据、过期、重复使用、hash/version 冲突均有状态与审计断言；未经批准不进入批准终态 | not_started |
| S6：人工接管 | 按 H0 reason/routing 契约、H1 case/event/outbox、H2 分派认领/SLA、H3 resolve 与审批绑定执行；工单关闭不等于 Claim 批准 | Handoff §5–14；Form 审批入口章节 | S5 | 重复 handoff 去重；case 状态/事件追加；并发认领和升级可验证；resolve 绑定合法 approval/version/hash | not_started |
| S7：表单 UI 与运营视图 | 先交付新建、草稿、编辑、提交、状态和审批结果主路径，再接入 case 时间线、待审列表和状态刷新；状态文案区分审批、工单关闭和付款 | Form §3、§8、§12 P3；Handoff 运营视图章节 | S4、S5；case 视图依赖 S6 | 浏览器主路径可完成；重复提交、网络失败、过期版本、越权状态有处理；无付款成功误导 | not_started |
| S8：验收与可选模型 | 按单测→dev→golden→held_out→HTTP/UI smoke→仓库回归执行；比较 S1 逐案证据；之后才可评估 JEV 类版本化候选模型 | Decision §8、§10.4–10.6 P5；Form §12 P4；Handoff 各阶段退出标准 | S3–S7 | 规则/审批/审计/人工作业端到端门禁通过，held_out 独立且不调参；候选模型可回退且不改变已冻结规则结果 | not_started |

## 4. 进度更新规则

- 每次状态变化同步更新本文件对应 S 阶段及来源 SPEC 的执行记录/验收勾选项，并附测试命令、报告路径或可复现证据。
- `complete` 只表示本阶段退出门槛全部满足；`in_progress` 表示正在实现；`blocked` 必须写明具体阻塞和解除条件；不得用整体通过率掩盖单项 known gap。
- 新增规则或改变状态/API 语义时，先更新其领域权威 SPEC 和 fixture，再更新本文件的映射与门槛。
- 不重写 S1 历史结果；候选批次使用新版本号和独立报告目录。
- S8 的 held_out 是冻结后的验收数据，不用于调参；外部系统、真实付款、生产 SLA 和合规能力不从模拟评测结果推断。

## 5. 下一步

进入 S3：基于 `EXPENSE_WORKFLOW_DECISION_SPEC.md` §5–6、§10.2–10.4 实现 `expense_claim_review@1`。先补充 Workflow 节点轨迹、失败关闭与幂等测试；将 2 个采购验证 known gap 纳入可信模拟 registry adapter 的验收。S4 Claim 持久化仍按顺序等待 S3 退出门槛通过。
