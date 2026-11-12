# Expense 跨 SPEC 实施总控规格

## 1. 文档职责

本文统一 `expense` 业务跨规格的实施顺序、依赖、阶段状态和退出门槛。S0–S8 是项目级执行序列，横跨多份业务规格；它们不是任一单独 SPEC 的内部批次编号。

本文只作为执行编排和进度索引，不复制领域规则、API 字段或状态机定义。领域语义发生冲突时，由下列来源规格负责定义；本文负责指出在哪个 S 阶段落实并验证这些语义。

| 来源文档 | 权威范围 |
|---|---|
| [`EXPENSE_POLICY_BOUNDARY_SPEC.md`](policy-boundary-spec.md) | 规则依据、规则优先级、政策边界和当前实现差距 |
| [`EXPENSE_WORKFLOW_DECISION_SPEC.md`](workflow-decision-spec.md) | 决策契约、规则决策模型、`expense_claim_review@1` 决策 Workflow、决策评测 |
| [`EXPENSE_FORM_WORKFLOW_SPEC.md`](form-workflow-spec.md) | Claim 表单 schema/lifecycle、正式审批入口、审批和持久化语义 |
| [`EXPENSE_HUMAN_HANDOFF_SPEC.md`](human-handoff-spec.md) | handoff reason、case、队列、认领、SLA 和人工处理流程 |

冲突裁决原则：政策含义以 Policy Boundary 和确认后的政策 fixture 为准；正式 Claim 状态与审批授权以 Form Workflow Spec 为准；决策对象及决策执行以 Decision Spec 为准；case 运营流程以 Human Handoff Spec 为准。总控文档不得覆盖这些定义。

## 2. 当前进度

状态按可检查的代码、测试和报告记录，不以计划文字推断完成。

| 阶段 | 状态 | 当前证据或未完成项 |
|---|---|---|
| S0 规格裁决 | complete | 政策边界和主要冲突已在来源规格中裁定；待确认项已转为明确模拟规则或显式延期项 |
| S1 基线冻结 | complete | [`S1_BASELINE_2026-10-12.md`](evidence/s1-baseline-20261012.md)：legacy 8 案、Expense 定向测试及 HTTP smoke；demo 环境阻塞如实记录 |
| S2 共享领域契约 | complete | `domain.py`、legacy adapter、契约测试和 candidate runner 已实现；报告在 `artifacts/expense/candidate-s2-20261012/` |
| S3 决策 Workflow | complete | `expense_claim_review@1` 已接通 HTTP（可选 workflow/legacy 回退）、demo、business evaluation 和 expanded candidate runner；采购/报价事实由可信模拟 adapter 提供，客户端自报验证字段不被信任；S3 smoke 与三组 candidate split 均通过 |
| S4 Claim 持久化 | complete | SQLAlchemy Claim/version/decision/audit/idempotency store 已接入；SQLite 契约测试和 PostgreSQL Compose 重启 smoke 覆盖创建、版本更新、提交冻结、恢复、幂等和冲突无副作用 |
| S5 审批闭环 | complete | `route_review` / `resolve_review` 已接入同一 SQL store；审批绑定 Claim 版本与 decision hash，支持 approve/reject/escalate、审计事件、重启恢复和幂等重放；不包含 S6 人工接管队列或 S7 UI |
| S6 人工接管 | in_progress | H0、[H1 存储验收](evidence/h1-case-storage.md)、[H2 限定切片](evidence/h2-case-operations.md)、[H3 审批衔接](evidence/h3-case-resolution.md) complete（存储切片）：H3 SQLite/PostgreSQL 各 31 项合同通过；相关存储合同 157 passed、1 SQLite TRUNCATE skipped；实际重启恢复审批结案、纯工单结案和等待补料，重复结案失败关闭。H4 通知与视图未实现；HTTP/自动建单未接通 |
| S7 表单 UI 与运营视图 | not_started | 独立表单主路径、待审列表和 case 时间线未实现 |
| S8 验收与可选模型 | not_started | 全链路验收尚未执行；JEV 类模型保持可选，且只能在规则/Workflow/审批门禁后评估 |

S2 candidate 结果：dev 41 案 39 通过、2 个采购验证 known gap（故 dev 命令为非零）；golden 12/12；held_out 16/16。held_out manifest hash 为 `f8801e86298c59260b8d510df9c965f953bcbc5430672fefdbb50b523457da36`。这些是离线候选规则/契约结果，不代表 Workflow、数据库、审批、人工作业或生产能力。

**S3 执行结果（2026-10-14）：** `artifacts/expense/smoke/s3/` 保存 dev/golden/held_out candidate 报告和 business evaluation 报告；candidate 为 dev 41/41、golden 12/12、held_out 16/16，business evaluation 8/8。Expense + Core Workflow 定向测试 68 项通过，compileall、ruff 和 `git diff --check` 通过。S3 入口已迁移到同一 Workflow：HTTP 仍可通过 `REACT_AGENT_EXPENSE_ENGINE=legacy` 回退；demo、business evaluation 和 candidate runner 均调用 `expense_claim_review@1`。`persist_decision` 已登记为 NOTIFY；Claim 状态持久化仍属于 S4。

**S4–S5 执行结果（2026-11-10）：** `ExpenseClaimStore` 使用项目数据库 URL 创建 Claim、不可变版本、决策、审批、追加式审计和幂等记录。SQLite 定向合同与 HTTP 生命周期测试覆盖提交路由、重启后待审恢复、人工批准终态恢复、decision hash/version 拒绝无副作用和 resolve 幂等重放。PostgreSQL 重启 smoke 入口为 `python scripts/eval/smoke/run_expense_postgres_restart_smoke.py --database-url <项目 Compose PostgreSQL URL> --restart-container`；该命令只创建并清理一个合成 Claim，不代表生产 SLA、多租户或真实财务系统接入。S5 仍不包含人工接管 case/队列、通知 outbox 或 UI。

## 3. 跨 SPEC 执行序列

每个阶段须通过自己的退出门槛后，才将状态更新为 complete。后续阶段可定义尚未实现的依赖，但不能把设计或 fixture 描述计为实现证据。

本执行序列区分两种关系：**发布依赖按 S3→S4→S5→S6→S7→S8 串行验收**，以便每个阶段都有稳定的可回滚边界；**开发工作可以在契约稳定后并行准备**，例如 S4 的存储接口、S7 的 UI 原型和 smoke 基础设施可以提前开发，但不能绕过前置阶段的退出门槛进入发布或把未接通的实现计为完成。

| 阶段 | 工作范围与交付 | 权威来源 | 依赖 | 退出门槛 | 状态 |
|---|---|---|---|---|---|
| S0：规格裁决 | 裁决规则优先级、`escalated` 非终态语义、Claim/Decision schema、审批入口、错误码、幂等边界；将未有依据的行为显式延期 | Policy Boundary §5；Decision §5–6；Form §5–11；Handoff §5–13 | 无 | 三份实施 SPEC 与政策边界不存在相互矛盾的对外语义；未决项有 owner/延期边界 | complete |
| S1：基线冻结 | 固定 legacy 决策、`ExpenseLedger`、`/v1/chat`、`expense_claim_review` 及旧 dev/golden/held_out 结果 | Decision §4、§8、§10；baseline report | S0 | 有可追溯报告、命令、fixture/代码版本、失败和环境限制；不覆盖后续历史 | complete |
| S2：共享领域契约 | 统一 Claim/version、Decision、ApprovalRecord、AuditEvent、Handoff reason、decision hash、错误码；保留 legacy adapter；实现扩展候选 fixture runner 和 held_out hash 保护 | Decision §6、§8、§10；Form §5、§11、§12 P0；Coverage Matrix | S0、S1 | 契约测试通过；旧入口回归；候选 runner 可执行并区分 pass/known_gap/fail；held_out hash 固定 | complete |
| S3：决策 Workflow | 将 `decide()` 包装为 `expense_claim_review@1`；以结构化 Claim→Workflow→HTTP/demo 输出作为第一个可运行垂直切片；实现固定节点、失败关闭、轨迹、决策审计适配和幂等重放；建立不依赖 LLM/外部财务系统的核心决策 smoke；对采购/报价证据使用 Workflow 控制的模拟 adapter，不信任客户端自报验证结果 | Decision §5、§6、§10 P2；Policy Boundary 决策规则；Coverage Matrix `W-ADAPTER-*` | S2 | 垂直切片可运行且可回退到 legacy；节点注册/顺序/成功跳过失败轨迹可断言；核心 smoke 覆盖批准、硬拒绝、人工审核、非法 Claim、政策不可用和幂等重放；规则输出与 S1 逐案兼容；未知或不可验证证据不得自动批准；`W-ADAPTER-*` 有测试 | complete |
| S4：持久化 Claim 生命周期 | 建 PostgreSQL Claim/version/audit store；实现 draft create/read/update、submit、版本冻结、状态迁移和查询；扩展持久化 smoke；Ledger 留作 legacy/eval adapter | Form §5–9、§11、§12 P1；Decision §6.3 | S3 | 重启后可查询的持久化 smoke 通过；提交冻结版本；重复请求幂等；版本冲突无副作用；审计完整 | complete |
| S5：审批闭环 | 将 `route_review` / `resolve_review` 接到 S4 SQL store；保存 pending review、resolution、审批状态和审计；Claim 版本与 decision hash 必须匹配，审批决议不绕过权限闸门 | Form §4–8、§11、§12 P2；Decision §6.3 | S4 | SQLite 合同、HTTP lifecycle 和 PostgreSQL 重启 smoke 覆盖 approve/reject/escalate、错误版本/hash、重复决议和审计；S6 case/队列与 S7 UI 仍延期 | complete |
| S6：人工接管 | 按 H0 reason/routing 契约、H1 case/event/outbox、H2 分派认领/SLA、H3 resolve 与审批绑定执行；扩展 handoff smoke；工单关闭不等于 Claim 批准 | Handoff §5–14；Form 审批入口章节 | S5 | 重复 handoff 去重；case 状态/事件追加；并发认领和升级可验证；handoff smoke 证明 resolve 绑定合法 approval/version/hash 且不会绕过审批 | in_progress |
| S7：表单 UI 与运营视图 | 先交付新建、草稿、编辑、提交、状态和审批结果主路径，再接入 case 时间线、待审列表和状态刷新；建立浏览器 UI smoke；状态文案区分审批、工单关闭和付款 | Form §3、§8、§12 P3；Handoff 运营视图章节 | S4、S5；case 视图依赖 S6 | 浏览器 smoke 完成“新建→保存→编辑→提交→待审→审批结果”；重复提交、网络失败、过期版本、越权状态有处理；无付款成功误导 | not_started |
| S8：验收与可选模型 | 按单测→dev→golden→held_out→HTTP/UI smoke→仓库回归执行；汇总分阶段 smoke 为发布报告；比较 S1 逐案证据；之后才可评估 JEV 类版本化候选模型 | Decision §8、§10.4–10.6 P5；Form §12 P4；Handoff 各阶段退出标准 | S3–S7 | 规则/审批/审计/人工作业端到端门禁通过；HTTP/UI smoke 与分阶段 smoke 全部通过并保留报告、版本、fixture hash、配置和失败日志；held_out 独立且不调参；候选模型可回退且不改变已冻结规则结果 | not_started |

### 3.1 分阶段 Expense smoke 任务与验收成果

Expense smoke 不回写或重算 S1 baseline；它是 S3 之后按能力增量建立的独立验证批次。每个阶段的 smoke 必须使用独立的报告目录，例如 `artifacts/expense/smoke/<batch>/`，并记录代码提交号、fixture/policy hash、配置快照、命令和失败日志。

| 阶段 | 执行任务 | 最小场景 | 验收成果 |
|---|---|---|---|
| S3 | 新增决策 Workflow smoke（建议测试入口为 `tests/apps/expense/test_expense_workflow_smoke.py`，具体文件名以实现 PR 为准） | 正常批准、缺收据拒绝、超额度拒绝、`needs_review`、非法 Claim、政策不可用失败关闭、同幂等键重放及冲突 | Workflow 注册名和节点顺序可断言；每个结果有结构化 `decision/error_code/failed_step/run_id`；与 S1 逐案决策码无回归；报告和 `EvaluationEpisode` 可复现；采购 known gap 已关闭或明确转为受控 review |
| S4 | 将 smoke 扩展到 Claim 持久化 | draft 创建/更新、submit 冻结、重启恢复、重复提交、版本冲突 | PostgreSQL 重启后状态和审计可恢复；重复请求不产生重复 Claim/事件；冲突路径无业务副作用；持久化 smoke 报告独立保存 |
| S5 | 将 smoke 扩展到审批闭环 | route review、approve、reject、escalate、过期凭据、错误 decision hash/version、重复使用审批 | 只有合法审批能改变 Claim 终态；拒绝/升级保持正确非批准语义；权限 blocked、过期和重放均有状态与审计证据 |
| S6 | 将 smoke 扩展到人工接管 | reason 路由、重复 handoff、认领、升级、resolve、过期 Claim/Decision | case/event/outbox 可追踪；重复 handoff 去重；resolve 必须绑定合法 approval/version/hash；关闭工单不会直接批准 Claim |
| S7 | 建立浏览器 UI smoke | 新建→保存→编辑→提交→待审→审批结果；网络失败、重复提交、过期版本、越权状态 | 主路径可完成；错误状态可恢复或明确展示；审批、工单关闭和付款文案不混淆；截图/日志和运行报告可追溯 |
| S8 | 汇总并执行完整 HTTP/UI 发布 smoke | `/health`、`/ready`、`/v1/info`、Expense HTTP 正常/拒绝/审核路径、Workflow/审批/handoff 关键路径、UI smoke | 生成单独的发布 smoke 报告；所有必需场景通过才允许进入 release gate；任一失败状态为 `hold`；不以 S1 历史通过替代当前批次验证 |

### 3.2 开发批次与发布阶段的映射

S0–S8 是跨规格的发布依赖阶段；P0–P5 是决策 Workflow 规格中的实现批次。两套编号不表示两条独立路线，开发时按下表映射：

| 发布阶段 | 主要实现批次 | 开发关系 | 合并/发布约束 |
|---|---|---|---|
| S1 | P0 | 已冻结，只读引用 | 不重写历史报告或 fixture hash |
| S2 | P1 | 已完成；为后续并行开发提供稳定契约 | 契约和 legacy 回归必须保持通过 |
| S3 | P2 | 主线垂直切片；可并行准备存储接口和 smoke 工具 | 未通过 S3 smoke 前不得切换默认入口 |
| S3→S5 | P3、P4 | 入口迁移、权限和幂等可分 PR 开发；依赖按阶段接通 | 入口切换必须保留 legacy 回退；写入门禁未通过不得产生业务副作用 |
| S6 | Handoff 规格对应实现批次 | 可在 S5 契约稳定后准备 case/event/outbox，但接入依赖审批结果 | 未通过 approval/version/hash 绑定测试不得宣称 handoff 完成 |
| S7 | Form 规格 P3 | UI 可提前做契约 mock 和静态路径，真实联调等待 S4/S5/S6 | UI smoke 必须使用已稳定的状态和错误码 |
| S8 | Form P4 + Decision P5（可选） | 只做最终汇总、回归和候选模型对比 | 所有必需 smoke、held_out 和逐案基线比较通过后才可 release |

开发并行只允许减少等待，不改变依赖方向。任何并行分支在合并前都必须通过其声明的契约测试，并在对应阶段报告中记录接通的真实路径；mock、fixture 或设计文档不能替代运行证据。

## 4. 进度更新规则

- 每次状态变化同步更新本文件对应 S 阶段及来源 SPEC 的执行记录/验收勾选项，并附测试命令、报告路径或可复现证据。
- `complete` 只表示本阶段退出门槛全部满足；`in_progress` 表示正在实现；`blocked` 必须写明具体阻塞和解除条件；不得用整体通过率掩盖单项 known gap。
- 新增规则或改变状态/API 语义时，先更新其领域权威 SPEC 和 fixture，再更新本文件的映射与门槛。
- 不重写 S1 历史结果；候选批次使用新版本号和独立报告目录。
- S8 的 held_out 是冻结后的验收数据，不用于调参；外部系统、真实付款、生产 SLA 和合规能力不从模拟评测结果推断。
- 开发任务可以并行进行，但阶段状态只能按依赖顺序更新；并行准备的接口、UI 或测试工具必须在实际路径接通后才计入阶段验收。
- S3 首先交付可运行垂直切片；后续阶段优先扩展同一条业务路径，避免分别维护无法联调的 demo、HTTP 和评测实现。

## 5. 下一步

S6 的 H0、H1 及本轮限定 H2 切片已完成，H1 的历史证据保持原样。H2 在 `ExpenseCaseStore` 上实现自认领、释放、转派、升级、冻结截止时间及幂等扫描。2026-11-12 重试 Docker 审批成功，检查全部 11 个容器并核对 Compose 归属后，复用当前项目 PostgreSQL 执行 H1/H2 合同（87 passed、1 skipped）和 H2 实际数据库重启检查；验证并发唯一认领、完整转派审计、锁与扫描标记恢复、重放不重复、超时仅解锁/升级不批准。未新建容器；测试 schema 已清理，为验收启动的三个项目容器已恢复原先停止状态。完整证据见 [H2 验证记录](evidence/h2-case-operations.md)。§9.2“连续两次无人认领”的轮次/重置时钟不在本切片冻结范围内，继续显式延期。

H3 的本轮存储切片已完成：`resolve_case` 绑定既有 approval_id、Claim/version/hash 和 case 版本，经现有 `resolve_review` 与权限闸门，在同一 SQL 事务保存审批、Claim 终态与 case 审计。无审批只能 complete 人工作业、不改 Claim；旧版本、重复 resolve、过期/拒绝/已消费/错绑凭据失败关闭。`start_case`、`request_applicant`、`resume_case` 明确开始、等待及申请人显式补料恢复；恢复仅回 queued，需重新认领，不重跑业务或重算 SLA。验证发现并修复直接 S5 与 H3 并发时的 SQLite 延迟事务缺口；PostgreSQL 统一 Claim→case→review 锁顺序。当前证据见 [H3 验证记录](evidence/h3-case-resolution.md)，不改写 H1/H2 历史结果。

S6 仍为 in_progress。所有 case 能力仍是存储接口，未接 HTTP/现有 `route_review` 自动建单；旧 S5 自由文本 reason 不在本轮重写，未来可信适配必须保持 Decision 指纹一致。H4 通知发送继续后置；只有既有合法 Expense 审批才能改变 Claim 批准结果，关工单不等于批准报销。保持 S4–S5 的 Claim/审批 SQL 事实来源，交付线、Go 后端、UI 和 `react_loop` 继续冻结。S8 的 held-out/golden、真实业务接入和生产 SLA 仍只作为后续验收边界，不从本轮契约测试推断。
