# Expense：Workflow + 决策模型规格说明

## 1. 文档状态

本文定义主线 **② 客服 / 工作流自动化** 下 `expense` 应用的决策层演进规格：由「政策片段 + 固定裁决」的 demo 骨架，升级为 **声明式 Workflow + 可插拔决策节点** 的业务编排样板。表单、任务生命周期和人工审批闭环另见 [`EXPENSE_FORM_WORKFLOW_SPEC.md`](EXPENSE_FORM_WORKFLOW_SPEC.md)。

它是实现与验收规格，不构成生产报销系统、财务合规或 SLA 承诺。

阶段 0 的政策边界、规则优先级、待业务确认项和当前实现覆盖矩阵见 [`EXPENSE_POLICY_BOUNDARY_SPEC.md`](EXPENSE_POLICY_BOUNDARY_SPEC.md)。在该文档第 5 节的待确认项完成前，本规格对应的 Expense 状态保持 **hold**。

**定位一句话：** `expense` 负责「已结构化政策/事实之后的拍板与状态变更」；不与 `docs_troubleshoot` 的检索/证据化搜索抢主场。

相关入口：

| 项 | 路径 |
|----|------|
| 应用代码 | `src/react_agent/apps/expense/` |
| Fixture | `fixtures/expense/`（claims / policy / business_cases） |
| 演示 | `demos/demo_expense_workflow.py` |
| HTTP app | `POST /v1/chat` · `app=expense` |
| 业务评测 | `scripts/eval/acceptance/run_expense_business_eval.py` |
| 主线地图 | [`APPLICATION_DIRECTION.md`](../APPLICATION_DIRECTION.md) §② |

## 2. 范围

### 2.1 包含（目标态）

- 固定步骤的 **决策 Workflow**（收单 → 取政策/事实 → 决策 → 写决策审计 → 返回父 Workflow 路由结果）。
- **决策模型节点**：当前由确定性的规则决策模型实现；未来可插入 JEV 类特化决策模型，但本规格不增加独立的模型建议器层。
- 结构化决策码与决策审计记录（离线评测可用 `ExpenseLedger`；正式任务由 PostgreSQL 后继存储承载）。
- 与 Core **权限闸门** 的衔接：写状态 / 外部副作用走 CONFIRM（或更高）；纯只读取政策可为 SAFE。
- 可复现评测：dev / golden / held_out 业务状态断言 + `EvaluationEpisode` 导出。
- Fixture 收敛于 `fixtures/expense/`，供 Workflow、demo、评测共用。

### 2.2 不包含

- 开放式多轮 ReAct「自由聊报销」（Live LLM 聊天不是本规格 KPI）。
- 与 `docs_troubleshoot` 合并成单一知识客服产品。
- 搜索/排序算法优化（召回、ranking、多跳检索属文档/RAG 线）。
- 真实财务系统对接、税务合规、多租户审批流引擎。
- 用模型直接输出不可复现的自由文本作为唯一裁决依据。

## 3. 分层职责

| 层 | 职责 | 成功标准 |
|----|------|----------|
| **Workflow** | 固定步骤与状态机：收单 → 取政策/事实 → 决策 → 写决策审计 → 返回父 Workflow | 步骤可枚举、可回放、失败可定位到节点 |
| **决策器** | 接收结构化 claim 与 policy facts，由当前规则决策模型或经评测的特化决策模型产出最终决策对象 | 决策码稳定、来源可追溯、例外有结构化字段 |
| **规则评估器** | 执行可枚举、可审计的硬约束和阈值规则 | 缺票、超额、审批级别等边界结果确定且可回放 |
| **决策模型** | 领域层的裁决实现；当前为规则模型，未来可替换为 JEV 类特化模型 | 只输出经过契约验证的结构化决策，不直接执行账本副作用 |
| **与 docs 边界** | `docs_troubleshoot` 管检索与证据；`expense` 消费已结构化的政策/事实 | KPI 不混用（见 §8） |

```text
HTTP / demo / eval
        |
        v
+------------------- Workflow -------------------+
| ingest_claim -> load_policy_facts -> decide    |
|      -> persist_decision -> route_or_finalize  |
+-------------------+----------------------------+
                    |
          +---------+---------+
          v                   v
   policy/facts adapter   decision node
   (structured fields)    (rules or specialized
                           decision model)
          |                   |
          +---------+---------+
                    v
            decision audit / claim adapter
                    |
                    v
            permission gate (writes)
```

## 4. 与现有代码的衔接

| 现状组件 | 规格中的角色 | 演进方向 |
|----------|--------------|----------|
| `offline_answer.decide()` | 规则评估器的兼容实现 | 保留为默认/失败关闭路径；签名稳定；不把它直接当作完整决策模型 |
| `ExpenseLedger` | 离线账本与幂等审计 adapter | legacy 评测记录；正式 claim 状态不以它为权威 |
| `fixtures/expense/*` | 政策语料、样例单、评测用例 | Workflow/评测唯一夹具根 |
| `demo_expense_workflow.py` | 口述用线性骨架 | 改为驱动同一 Workflow 定义（或薄包装） |
| `react_agent.workflow` | Core 声明式引擎 | expense 注册为 app 级 workflow，不再只靠脚本顺序 |
| `safety/permission_gate` | 写副作用闸门 | `decide_claim` / 外部通知等登记权限等级 |

**当前（基线）：** `app=expense` 走 `offline_answer.answer_offline()`——keyword RAG 取政策片段 + `decide()`；LLM Live 返回 501；基本无工具循环。

**目标：** 同一业务语义由 Workflow 编排表达；决策器通过稳定契约调用当前规则决策模型，并为未来 JEV 类特化决策模型保留可替换边界；黄金集关键路径必须可复现。

## 5. Workflow 契约

### 5.1 决策执行状态

```text
decision_pending -> decision_ready
                 -> decision_rejected
                 -> decision_needs_review
```

- 本规格只负责生成并审计决策对象；正式 claim 生命周期由
  [`EXPENSE_FORM_WORKFLOW_SPEC.md`](EXPENSE_FORM_WORKFLOW_SPEC.md) 所定义的父 Workflow 管理。
- `decision_rejected` 表示决策码为 `reject_*`，不等同于已经完成审批写入。
- `decision_needs_review` 表示需要人工审批或人工接管。任何 `escalated` 结果都必须保持非终态，不能自动映射为 `approved`。
- 离线 legacy adapter 可以继续把 `approve_*` 映射为 `ExpenseLedger` 的 `approved` 快照，以保持历史评测兼容；该映射不适用于正式表单任务。
- 决策重放按决策幂等键返回原结果；冲突不得写入任何业务状态。

### 5.2 节点（MVP）

| 节点 ID | 输入 | 输出 | 失败策略 |
|---------|------|------|----------|
| `ingest_claim` | HTTP body / 可解析字段 | 结构化 `claim` | 缺类目/金额 → 拒答（`refused`） |
| `load_policy_facts` | claim + `fixtures/expense/expense_policy.md` | 结构化额度/规则事实 | 语料缺失 → 失败关闭 |
| `decide` | claim + policy facts | `decision` 码 + 结构化理由 | 见 §6 |
| `persist_decision` | decision + decision_idempotency_key | 决策审计 / 适配器快照 | 重复 key 返回原结果；冲突 key 报错 |
| `finalize` | decision audit / adapter 快照 | HTTP/demo 响应 | — |

节点顺序固定；MVP 不允许模型自行增删节点。

### 5.3 决策码（稳定枚举）

至少保留：`reject_no_receipt`、`reject_over_limit`、`approve_manager`、`approve_finance`、`approve_director`、`escalated`。
其中 `escalated` 是非终态决策码，只能触发父 Workflow 的人工审批/接管路径，不能直接产生 `approved` claim。
扩展新码必须同步：`fixtures/expense/business_cases.json`、规则表、中文说明映射。

## 6. 决策模型契约

### 6.0 术语边界与适用场景

本规格中的“决策模型”是业务领域的 **Decision Model / Decisioner**，不是泛指任何 LLM。当前实现是确定性的规则决策模型；未来接入 JEV 类特化模型时，它必须直接实现同一决策模型契约，并接受同一套规则约束、版本管理和业务评测。本项目当前不需要独立的“模型建议器”：文本解析、字段归一化和异常检测只有在存在明确业务需求及可验证实现时才单独立项。

| 场景 | 规则评估器 | 决策模型/决策器 | 是否允许直接写账本 |
|------|------------|----------------|--------------------|
| 已有结构化类目、金额、凭证和预审批字段 | 评估硬规则和审批阈值 | 当前规则模型选择最终决策码并生成理由；未来特化模型必须遵守同一输出契约 | 通过 `persist_decision`；claim 状态由父 Workflow 闸门修改 |
| 缺少必填字段或字段类型错误 | 拒绝进入决策 | 返回 `invalid_claim` / `refused` | 不允许 |
| 文本中的类目、金额或凭证状态需要归一化 | 校验归一化后的值 | 只有在形成结构化 claim 后才能运行决策模型 | 不允许，直到结构化字段通过校验 |
| 规则明确拒绝（缺票、超额且无预批） | 直接产生拒绝事实 | 决策模型不得覆写硬规则 | 仅可持久化拒绝结果 |
| 规则未覆盖、政策冲突或疑似例外 | 标记 `not_covered` / `needs_review` | 选择升级或人工复核；特化模型也不能绕过该路径 | 不允许自动批准 |
| 重复请求、状态已终结或幂等 key 冲突 | 校验状态和幂等约束 | 返回原结果或结构化冲突 | 冲突时不写入 |

因此，“规则优先”描述的是硬约束，而不是要求额外增加一个建议器。最终裁决权属于通过契约验证的决策模型；决策审计由 `persist_decision` 写入，claim 状态由经过权限闸门的父 Workflow 写入。

### 6.1 优先级

1. **输入校验与归一化**：先得到结构化 claim；归一化失败时拒答，不进入写入路径。
2. **规则评估器**：评估缺票、额度、预审批、金额审批级别等硬约束；命中硬拒绝时，后续建议不得翻转结果。
3. **决策模型执行/仲裁**：当前调用规则决策模型，生成稳定 `decision`、理由、来源和是否需要升级；未来特化模型只能通过版本化适配器接入。规则未覆盖时必须选择 `needs_review`/`escalated`，不能猜测通过。
4. **人工/审批闸门**：处理高风险例外及所有外部副作用；通过后才允许父 Workflow 的 `resolve_review` 改变 claim 状态。

默认使用规则决策模型。未来特化决策模型上线前必须以独立版本进行 off/on 对比；它不得改变已通过 golden / held_out 用例的最终决策码，异常或输出非法时回退规则模型或升级路径。

### 6.2 输出形状（决策节点）

```json
{
  "decision": "approve_finance",
  "reasons": ["amount_gt_200", "has_receipt"],
  "decision_source": "rules",
  "decision_model": "expense-rules-v1",
  "rule_result": "matched",
  "review_required": false,
  "risk_score": 0.0,
  "exception_suggested": false,
  "handoff": null,
  "policy_refs": ["expense_policy.md#审批流"]
}
```

- `decision` 必填，且属于 §5.3 枚举（或经版本化扩展）。
- `decision_source` 至少区分 `rules`、`specialized_model`、`human_review`。
- `decision_model` 是决策模型名称和版本，例如 `expense-rules-v1` 或未来的 `jev-expense-v1`。
- `rule_result` 至少区分 `matched`、`rejected`、`not_covered`；`not_covered` 不得自动写成批准。
- `review_required=true` 或 `rule_result=not_covered` 时必须输出 `handoff`，其中至少包含 `reason_code`、`risk_level`、`amount_band` 和确定性 `decision_hash`；缺失这些字段不得进入人工接管路由。
- `decision_hash` 定义为对规范化 JSON（`claim_id`、`claim_version`、`policy_version`、`decision`、`reasons`、`decision_model`、`rule_result`、`handoff`）按固定字段顺序、UTF-8、无空白序列化后计算的 SHA-256；计算该 hash 时，`handoff.decision_hash` 不纳入 payload，计算完成后再将结果写入 handoff，避免递归定义。任何其他纳入字段变化都产生新 hash。
- `reasons` 为机器可读标签；对外 `answer` 可由模板渲染。正式表单评测以 `decision` + claim 状态 + 审计事件为准；离线 legacy 评测才使用 `ExpenseLedger` 状态适配。

### 6.3 与权限闸门

| 动作 | 建议权限等级 |
|------|----------------|
| 只读政策 / inspect claim | SAFE 或 NOTIFY |
| `persist_decision` / 写决策审计 | SAFE 或 NOTIFY；若同时改变 legacy ledger 则走 CONFIRM |
| `resolve_review` / 改 claim 状态 | CONFIRM |
| 对外通知、打款、写外部系统 | CONFIRM；未接入前不得伪造成功 |

生产异步审批遵循 `REACT_AGENT_APPROVAL_MODE` 既有语义；本规格不重新定义闸门协议。

## 7. 与 docs_troubleshoot / RAG 的边界

| | `docs_troubleshoot` | `expense`（本规格） |
|--|---------------------|---------------------|
| 主问题 | 技术文档/Runbook：检索、引用、拒答、证据 | 制度政策下的审批裁决与状态 |
| 输入 | 自然语言问题 ± 现场证据 | 结构化 claim（可从文本解析） |
| 输出 | 带 citation 的答案 / 诊断 | 决策码 + claim 状态（legacy 离线适配时才映射 ledger） |
| KPI | 引用命中、拒答正确、检索质量 | 决策正确率、升级路径、状态一致性、幂等 |
| 检索 | 核心能力（可向搜索算法演进） | 仅 Workflow 内「取政策事实」适配步骤 |

`expense` 不得依赖开放域文档检索质量作为主验收；政策文件以 `fixtures/expense/expense_policy.md` 为权威输入。

## 8. 评测与验收

### 8.1 必保

- `run_expense_business_eval` （或后继）在 dev/golden/held_out 上通过状态断言。
- 决策码与 `expected_state` 一致；同一作用域内的幂等键重复调用不双写。
- Fixture 根目录为 `fixtures/expense/`。

### 8.2 Workflow MVP 验收清单

- [x] expense 存在可运行的 Workflow 定义（注册名稳定，可被 Workflow API 与 HTTP opt-in 离线路径调用；demo 入口迁移仍待 P3）。
- [x] 节点顺序与 §5.2 一致；轨迹或步骤日志能指出失败节点。
- [x] 默认决策路径纯规则，不调用 LLM。
- [ ] 默认规则决策模型结果与当前 `decide()` 基线逐案一致。
- [ ] 决策审计与父 Workflow 状态写入路径分别经过权限闸门登记。
- [ ] `docs_troubleshoot` 黄金集 / git-docs 不因本规格文档新增而错误失败（语料基线按仓库约定刷新）。

### 8.3 非目标指标

不将检索 MRR、开放问答满意度、Live ReAct 步数作为 expense 发布门禁。

## 9. 配置（预留）

```env
REACT_AGENT_EXPENSE_DECISION_MODEL=off
REACT_AGENT_EXPENSE_FIXTURE_DIR=
REACT_AGENT_EXPENSE_ENGINE=workflow
```

具体键名以实现 PR 为准；新增键须更新 [`DEPLOY.md`](../operations/DEPLOY.md)。

## 10. 里程碑

| 阶段 | 交付 | 退出标准 |
|------|------|----------|
| **M0** | Fixture 收敛至 `fixtures/expense/`；规则 `decide` + ledger 评测 | 路径单一、评测绿 |
| **M1** | Workflow 包裹现有规则路径；demo/HTTP 离线切到同一编排 | §8.2 编排项打勾；基线决策一致 |
| **M2** | 决策节点输出 §6.2 形状；权限登记写路径 | 契约测试 + 闸门测试 |
| **M3** | 可插拔特化决策模型接口（例如 JEV 类实现），默认仍使用规则模型 | 候选模型不改变 golden/held_out；规则模型可随时回退 |
| 之后 | 真挂起态 `escalated`、外部审批回调、多政策版本 | 另开规格修订 |

### 10.1 执行计划（按依赖顺序）

本节把上表拆成可独立评审的交付批次。每一批都必须先通过自己的退出标准，再进入下一批；不允许在同一个变更中同时切换 HTTP、demo、评测和特化决策模型路径。

| 批次 | 目标 | 主要改动 | 交付证据 | 失败时处理 |
|------|------|----------|----------|------------|
| **P0 基线冻结** | 固定现有行为，建立迁移前参照 | 不改业务代码；记录当前 `pytest`、业务评测、demo 和 HTTP smoke 结果 | 基线报告、命令、提交号、fixture 版本 | 只修复环境/测试问题，不修改基线语义 |
| **P1 契约与 Fixture** | 统一输入、政策事实、决策输出和错误码 | 拆出共享的 claim/policy/decision 结构；校验 `business_cases.json` 与决策码映射；保留 `decide()` 签名 | 契约测试；所有现有用例可由同一 loader 读取 | 继续使用旧 loader；不得改写 dev/golden/held_out 历史记录 |
| **P2 Workflow 包装** | 让规则路径由 Core Workflow 可回放地执行 | 新增 `src/react_agent/apps/expense/workflow.py`；注册 `expense_claim_review@1`；实现 §5.2 五个节点；保留 legacy adapter；增加模拟证据 adapter | Workflow 注册/运行测试；节点轨迹包含成功、跳过和失败节点；S3 smoke 覆盖规则、失败关闭、幂等和 adapter | 通过 `REACT_AGENT_EXPENSE_ENGINE=legacy` 回退，规则结果必须相同；完整入口迁移留在 P3 |
| **P3 入口切换** | HTTP、demo、业务评测共用同一编排 | `chat_router.py`、`demo_expense_workflow.py`、`run_expense_business_eval.py` 改调用 Workflow adapter；保留原响应字段 | HTTP smoke、demo 输出、评测全量通过；逐案与 P0 比较无回归 | 仅回退入口，不回滚契约和审计字段 |
| **P4 写入与权限** | 将决策审计和 claim 状态写入纳入可观察的权限闸门 | 给 `persist_decision` 和父 Workflow 的状态写入增加幂等重放和冲突错误；补充权限表/测试；只读节点保持 SAFE | gate allow/blocked 两条路径、重复 key、冲突 key 的测试和轨迹 | gate 未通过时不改变业务状态；返回结构化 `approval_required` 或拒绝 |
| **P5 特化决策模型（可选）** | 引入 JEV 类特化决策模型作为规则模型的候选实现，不增加旁路建议器 | 拟新增版本化 `DecisionModel` 适配器；超时、非法输出、未知决策码均回退规则模型或升级 | 规则模型/候选模型双跑；golden/held_out 逐案决策码和状态不变 | 关闭候选模型配置并回到 P4 规则路径，不重写历史证据 |

建议的 PR 边界为：P0/P1（契约与夹具）、P2（Workflow 注册）、P3（入口迁移）、P4（权限与幂等）、P5（特化决策模型）。一个 PR 不跨越两个发布门禁，评测报告与代码变更一起提交。

**P0 执行记录（2026-10-12）：** 基线报告见 [`S1_BASELINE_2026-10-12.md`](../evaluation/expense/S1_BASELINE_2026-10-12.md)。Expense 定向测试 27/27、dev 2/2、golden 3/3、held_out 3/3，HTTP 路由 smoke 1/1；demo 因 Windows ACL 阻止临时 `biz.json` 写入而未能完成，已在报告中记录为环境阻塞。原始评测报告与 episode 保存在 `artifacts/expense/s1-baseline-20261012/`；该目录受 `.gitignore` 忽略，提交基线说明不会自动提交这些原始文件。

**S2 执行记录（2026-10-12）：** 新增 `src/react_agent/apps/expense/domain.py` 作为共享领域契约，覆盖版本化 Claim、Decision、Handoff、ApprovalRecord、AuditEvent、稳定错误码和 legacy Claim adapter；`offline_answer` 的旧入口先经 adapter 归一化，保留原响应字段和决策码。契约测试新增 12 项，Expense 定向测试合计 40/40 通过。Decision hash 对规范 payload 计算；为避免 `handoff.decision_hash` 的递归定义，hash payload 排除该嵌套字段，计算完成后再回填到 handoff。S2 不包含正式 Claim 持久化、审批 Workflow、HTTP 入口切换或外部系统写入。

**S2 后候选 Runner 执行记录（2026-10-12）：** 新增 `candidate_eval.py` 和 `run_expense_candidate_eval.py`，实现 expanded fixture 的模板展开、显式 `null` 覆盖、逐字段断言、`EvaluationEpisode` 导出、split 隔离和 held_out manifest hash 校验。dev 41 案中 39 通过、2 个采购外部验证 known gap，命令以 exit 1 阻止进入 Workflow；golden 12/12；held_out 显式授权只读执行后 16/16，hash 保持 `f8801e86298c59260b8d510df9c965f953bcbc5430672fefdbb50b523457da36`。住宿按晚计算、交通超额、`pre_approved` 类型和娱乐缺少业务目的的规则缺口已关闭。候选结果不替代 S1 基线，也不表示 Workflow 已实现。

**S3 执行记录（2026-10-14）：** 新增 `src/react_agent/apps/expense/workflow.py` 并注册 `expense_claim_review@1`，实现 `ingest_claim`、`load_policy_facts`、`decide`、`persist_decision`、`finalize` 五节点；HTTP 通过 `REACT_AGENT_EXPENSE_ENGINE=workflow` 选择新路径，默认仍保留 legacy。新增 `SimulationEvidenceAdapter`，采购/报价事实由 adapter 提供，客户端自报的 `purchase_order_verified` 不被信任。demo、business evaluation 和 candidate runner 已改为调用同一 Workflow；`persist_decision` 已在权限表登记为 `NOTIFY`。`tests/apps/expense/test_expense_workflow_smoke.py` 覆盖批准、硬拒绝、人工审核、非法 Claim、政策损坏/未知决策码失败关闭、幂等重放与冲突、采购/报价 adapter、HTTP workflow 与 legacy 回退；Expense + Core Workflow 定向测试合计 68 项通过。candidate dev 41/41、golden 12/12、held_out 16/16，business evaluation 8/8；报告保存在 `artifacts/expense/smoke/s3/`。S3 已满足退出门槛并标记为 `complete`；pytest cache 目录权限警告不影响测试结果。

### 10.2 目标状态与节点数据契约

Workflow 的共享状态使用稳定键，节点不得依赖未声明的隐式全局变量。决策 Workflow 是表单父 Workflow 在 `submit` 后调用的子流程；它只返回决策对象和审计结果，不拥有 claim 的 `approved`、`rejected` 或 `escalated` 状态迁移。以下是 MVP 的最小状态形状；额外字段只能追加，不能改变已有字段含义：

```json
{
  "claim": {"id": "C-001", "category": "餐饮", "amount": 128, "has_receipt": true, "pre_approved": false},
  "claim_valid": true,
  "policy_facts": {"limits": {"餐饮": 200}, "policy_version": "fixture-v1"},
  "decision": {
    "decision": "approve_manager",
    "reasons": ["amount_lte_200", "has_receipt"],
    "risk_score": 0.0,
    "exception_suggested": false,
    "decision_model": "expense-rules-v1",
    "decision_source": "rules",
    "rule_result": "matched",
    "review_required": false,
    "handoff": null,
    "policy_refs": ["expense_policy.md#审批流"]
  },
  "decision_audit": {"claim_id": "C-001", "decision": "approve_manager"},
  "decision_idempotency_key": "C-001:v1:decision",
  "answer": "...",
  "error_code": ""
}
```

节点约束如下：

1. `ingest_claim` 只负责解析和字段校验。缺少 `category`、`amount` 或无法转换金额时，设置 `claim_valid=false`、`error_code=invalid_claim`，不调用政策和写入节点。
2. `load_policy_facts` 从 `fixtures/expense/expense_policy_v2.json` 读取版本化额度与类别事实，并从 `expense_policy.md` 提供引用锚点。JSON 无法解析、类别事实无效或政策版本不一致时失败关闭，不能使用默认额度掩盖 fixture 损坏。正式表单任务使用同一结构化 policy facts loader；不得另建一套额度规则。
3. `decide` 先调用现有硬规则；未知类目、未知决策码或规则异常都产生结构化错误，不允许模型直接生成最终码。
4. `persist_decision` 只接受已验证的 `decision` 和 `decision_idempotency_key`。重复 key 返回原结果并标记 `idempotent_replay=true`；同 key 对应不同 claim、版本或决策产生 `idempotency_conflict`，且业务状态不变。
5. `finalize` 只负责把 WorkflowResult 渲染为 HTTP/demo/评测需要的输出；不得在该节点追加业务写入。claim 状态由表单父 Workflow 的 `route_review` / `resolve_review` 处理。

失败结果至少包含 `ok=false`、`error_code`、`failed_step`、`run_id` 和步骤轨迹。对外 `answer` 可以是模板文本，但验收只依赖结构化决策、状态、错误码和引用。

### 10.3 文件级实施清单

| 文件 | 计划动作 | 约束 |
|------|----------|------|
| `src/react_agent/apps/expense/workflow.py` | 构造 `WorkflowDef`、节点 handler、输出适配器和模拟证据 adapter | 不复制 `decide()` 规则；版本名固定为 `expense_claim_review@1` |
| `src/react_agent/workflow/builtins.py` | 注册 expense Workflow，或调用 expense 模块的注册函数 | 不改变 `docs_troubleshoot` 的步骤和版本 |
| `src/react_agent/apps/expense/offline_answer.py` | 保留解析/规则兼容函数；必要时委托共享契约 loader | 旧调用方的字段和决策码保持兼容 |
| `src/react_agent/apps/expense/operations.py` | 保留 legacy ledger adapter，增加决策幂等重放标记和冲突错误 | 不改变已有 `snapshot()` 的字段含义 |
| `src/react_agent/server/chat_router.py` | P3 切换到 Workflow adapter | 保留 `answer`、`decision`、`claim`、`citations`、`mode` 等现有响应字段 |
| `demos/demo_expense_workflow.py` | 仅保留输入展示和结果展示，实际执行调用注册 Workflow | demo 与 HTTP 不各自实现一套规则 |
| `src/react_agent/apps/expense/eval_business.py` | 增加 Workflow reference agent 或 adapter | `EvaluationEpisode` 保留原 schema 和逐案状态断言 |
| `scripts/eval/acceptance/run_expense_business_eval.py` | 增加 engine/version、报告路径和比较信息 | held_out 仍独立报告，不与 dev/golden 合并统计 |
| `src/react_agent/safety/permissions.py` | 登记决策审计与 claim 状态写动作的权限等级 | 只读政策/inspect 不得被误标为写入 |
| `tests/apps/expense/test_expense_workflow_smoke.py` | Workflow 注册、节点顺序、失败关闭、输出契约、幂等和模拟 adapter smoke | 测试不依赖真实 LLM 或外部财务系统；权限测试留在 P4 |
| `docs/operations/DEPLOY.md` | P3 后补充配置键和响应示例 | 配置默认值与本规格一致 |

### 10.4 测试与验收矩阵

| 层级 | 最小覆盖 | 发布门槛 |
|------|----------|----------|
| 规则单元 | 缺票、额度边界、超额无预批、预批、金额审批级别、未知类目 | 决策码与现有基线逐案一致 |
| 契约测试 | claim 输入、policy facts、decision 输出、错误码枚举、引用锚点 | 非法输入不进入写入节点；未知码不能 finalize |
| Workflow 集成 | 注册名/版本、五节点顺序、失败节点、轨迹、`WorkflowResult.to_dict()` | `ok`、`failed_step`、`run_id` 和步骤数可断言 |
| Ledger/权限 | 首次写入、同 key 重放、冲突 key、gate blocked、审批后重试 | blocked 路径 ledger 状态和审计事件数均不变 |
| 入口回归 | demo、`POST /v1/chat`、旧结构化 claim 和文本解析 | 旧响应字段保留，HTTP 状态码语义无无意回归 |
| 业务评测 | dev、golden、held_out、`EvaluationEpisode` 导出、reference 对比 | 全部通过；任何已通过用例回归即 hold |
| 特化决策模型 | 规则模型、候选 JEV 类模型、非法输出、超时、未知决策码 | 候选模型必须与规则基线逐案比较；失败时回退或升级 |

推荐的验证顺序为：先运行 expense 定向单测，再运行 `run_expense_business_eval.py --split dev`、`--split golden`、`--split held_out`，然后运行 HTTP smoke，最后再执行仓库回归测试。held_out 原始 episode、报告和失败日志必须保留，不覆盖历史文件。

### 10.5 配置、迁移和回滚

迁移期间暂时允许 `REACT_AGENT_EXPENSE_ENGINE=legacy|workflow`，默认仍按当前部署环境选择；完成 P3 且连续一轮完整评测通过后，才把新部署默认改为 `workflow`。`REACT_AGENT_EXPENSE_DECISION_MODEL=off` 必须保持默认值。

切换前后都记录：代码提交号、配置快照、fixture 哈希、评测报告路径、各 split 的用例数/通过率、逐案差异和 Workflow 版本。若出现任何决策码、终态、幂等计数或权限结果回归：

1. 立即把入口切回 `legacy`，保留失败的 Workflow episode 和日志；
2. 定位到具体节点或契约字段后，补回归测试；
3. 重新创建候选批次并完整跑 dev/golden/held_out；
4. 不修改既有 held_out 结果来掩盖回归，也不把特化决策模型失败计入规则模型基线失败。

### 10.6 发布门禁与证据边界

决策 Workflow MVP 只承诺离线 fixture、可复现决策行为和决策审计。`ExpenseLedger` 仅是离线评测/legacy adapter；正式 claim、approval、case 和 audit 的业务事实来源由表单与人工接管规格统一规定为 PostgreSQL。真实财务系统写入、生产审批 SLA、并发持久化一致性、多租户隔离、税务合规和真实流量效果必须单独标记为未覆盖。

发布前必须同时满足：

- P0 基线报告可追溯，且 P3 后逐案比较无回归；
- dev/golden/held_out 的状态断言和 `EvaluationEpisode` 均通过，held_out 仍保持独立统计；
- 决策审计和 claim 状态写入在权限闸门中有明确等级，blocked/approval_required 不产生业务副作用；
- Workflow 轨迹能够定位失败节点，报告包含版本、fixture 和配置来源；
- `docs_troubleshoot` 既有测试与评测不因 expense 注册或 fixture 变更而回归。

未满足任一项时，状态为 **hold**，不得称为生产就绪，也不得以开放式问答质量或检索指标替代 expense 业务门禁。

## 11. 修订规则

- 变更决策码枚举、节点表或状态机：必须改本文件并写入修订记录。
- 纯实现重构、不改对外决策语义：可只改代码与测试。
- 与 Redis 任务队列、沙箱等横切能力交叉时，以各专项规格为准。

### 修订记录

| 日期 | 说明 |
|------|------|
| 2026-10-10 | 初稿：② 主线下 Workflow + 决策模型目标态与边界 |
| 2026-10-10 | 增补：按 PR 的实施批次、状态/错误契约、文件清单、测试矩阵、迁移回滚与发布门禁；目标与非目标不变 |
