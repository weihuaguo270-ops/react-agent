# Expense：Workflow + 决策模型规格说明

## 1. 文档状态

本文定义主线 **② 客服 / 工作流自动化** 下 `expense` 应用的演进规格：由「政策片段 + 固定裁决」的 demo 骨架，升级为 **声明式 Workflow + 可插拔决策节点** 的业务编排样板。

它是实现与验收规格，不构成生产报销系统、财务合规或 SLA 承诺。

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

- 固定步骤的 **Workflow 状态机**（收单 → 取政策/事实 → 决策 → 写账本/升级 → 出结论）。
- **决策模型节点**：规则优先；可选模型只做分类 / 风险分 / 例外建议。
- 结构化决策码与账本副作用（`ExpenseLedger` 或其后继）。
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
| **Workflow** | 固定步骤与状态机：收单 → 取政策/事实 → 决策 → 写账本/升级 → 出结论 | 步骤可枚举、可回放、失败可定位到节点 |
| **决策模型** | 闸门内的「拍板」节点：规则优先；模型仅分类 / 风险分 / 例外建议 | 关键路径决策码稳定；例外有结构化字段 |
| **与 docs 边界** | `docs_troubleshoot` 管检索与证据；`expense` 消费已结构化的政策/事实 | KPI 不混用（见 §8） |

```text
HTTP / demo / eval
        |
        v
+------------------- Workflow -------------------+
| ingest_claim -> load_policy_facts -> decide    |
|      -> persist_ledger -> escalate_or_finalize |
+-------------------+----------------------------+
                    |
          +---------+---------+
          v                   v
   policy/facts adapter   decision node
   (structured fields)    (rules +/- model)
          |                   |
          +---------+---------+
                    v
            ExpenseLedger / audit
                    |
                    v
            permission gate (writes)
```

## 4. 与现有代码的衔接

| 现状组件 | 规格中的角色 | 演进方向 |
|----------|--------------|----------|
| `offline_answer.decide()` | 决策节点的规则实现 | 保留为默认/失败关闭路径；签名稳定 |
| `ExpenseLedger` | 账本与幂等审计 | Workflow「写账本」步骤的系统记录 |
| `fixtures/expense/*` | 政策语料、样例单、评测用例 | Workflow/评测唯一夹具根 |
| `demo_expense_workflow.py` | 口述用线性骨架 | 改为驱动同一 Workflow 定义（或薄包装） |
| `react_agent.workflow` | Core 声明式引擎 | expense 注册为 app 级 workflow，不再只靠脚本顺序 |
| `safety/permission_gate` | 写副作用闸门 | `decide_claim` / 外部通知等登记权限等级 |

**当前（基线）：** `app=expense` 走 `offline_answer.answer_offline()`——keyword RAG 取政策片段 + `decide()`；LLM Live 返回 501；基本无工具循环。

**目标：** 同一业务语义由 Workflow 编排表达；决策节点可替换/可旁路模型建议，但黄金集关键路径仍由规则保证复现。

## 5. Workflow 契约

### 5.1 状态机（报销单）

```text
pending -> approved
       -> rejected
       -> escalated   # 需更高审批层级；MVP 可先与 approve_* 映射为 approved 并保留 decision 码
```

- `approved` / `rejected` 为终态；重复决策必须幂等（已有 `idempotency_key` 语义须保留）。
- `escalated` 在 MVP 可先不拆真挂起；与现 `ExpenseLedger` 对齐（`approve_*` → `approved` + `decision` 字段）。

### 5.2 节点（MVP）

| 节点 ID | 输入 | 输出 | 失败策略 |
|---------|------|------|----------|
| `ingest_claim` | HTTP body / 可解析字段 | 结构化 `claim` | 缺类目/金额 → 拒答（`refused`） |
| `load_policy_facts` | claim + `fixtures/expense/expense_policy.md` | 结构化额度/规则事实 | 语料缺失 → 失败关闭 |
| `decide` | claim + policy facts | `decision` 码 + 结构化理由 | 见 §6 |
| `persist_ledger` | decision + idempotency_key | 更新后的 claim / audit | 重复 key 返回原结果；冲突 key 报错 |
| `finalize` | ledger 快照 | HTTP/demo 响应 | — |

节点顺序固定；MVP 不允许模型自行增删节点。

### 5.3 决策码（稳定枚举）

至少保留：`reject_no_receipt`、`reject_over_limit`、`approve_manager`、`approve_finance`、`approve_director`。
扩展新码必须同步：`fixtures/expense/business_cases.json`、规则表、中文说明映射。

## 6. 决策模型契约

### 6.1 优先级

1. **硬规则**（缺票、超额度且无预批等）→ 直接产出决策码。
2. **模型建议**（可选）→ 仅可影响：类目归一、风险分、是否建议人工例外。
3. **人工/审批闸门** → 外部副作用或高风险例外。

默认关闭模型建议；开启后黄金集 / held_out 上规则可单独跑通的用例不得因模型开启而失败。

### 6.2 输出形状（决策节点）

```json
{
  "decision": "approve_finance",
  "reasons": ["amount_gt_200", "has_receipt"],
  "risk_score": 0.0,
  "exception_suggested": false,
  "model_used": false,
  "policy_refs": ["expense_policy.md#审批流"]
}
```

- `decision` 必填，且属于 §5.3 枚举（或经版本化扩展）。
- `reasons` 为机器可读标签；对外 `answer` 可由模板渲染。**评测断言以 `decision` + ledger 状态为准。**

### 6.3 与权限闸门

| 动作 | 建议权限等级 |
|------|----------------|
| 只读政策 / inspect claim | SAFE 或 NOTIFY |
| `persist_ledger` / 改 claim 状态 | CONFIRM |
| 对外通知、打款、写外部系统 | CONFIRM；未接入前不得伪造成功 |

生产异步审批遵循 `REACT_AGENT_APPROVAL_MODE` 既有语义；本规格不重新定义闸门协议。

## 7. 与 docs_troubleshoot / RAG 的边界

| | `docs_troubleshoot` | `expense`（本规格） |
|--|---------------------|---------------------|
| 主问题 | 技术文档/Runbook：检索、引用、拒答、证据 | 制度政策下的审批裁决与状态 |
| 输入 | 自然语言问题 ± 现场证据 | 结构化 claim（可从文本解析） |
| 输出 | 带 citation 的答案 / 诊断 | 决策码 + ledger 状态 |
| KPI | 引用命中、拒答正确、检索质量 | 决策正确率、升级路径、状态一致性、幂等 |
| 检索 | 核心能力（可向搜索算法演进） | 仅 Workflow 内「取政策事实」适配步骤 |

`expense` 不得依赖开放域文档检索质量作为主验收；政策文件以 `fixtures/expense/expense_policy.md` 为权威输入。

## 8. 评测与验收

### 8.1 必保

- `run_expense_business_eval` （或后继）在 dev/golden/held_out 上通过状态断言。
- 决策码与 `expected_state` 一致；`idempotency_key` 重复调用不双写。
- Fixture 根目录为 `fixtures/expense/`。

### 8.2 Workflow MVP 验收清单

- [ ] expense 存在可运行的 Workflow 定义（注册名稳定，可被 demo 与 HTTP 离线路径调用）。
- [ ] 节点顺序与 §5.2 一致；轨迹或步骤日志能指出失败节点。
- [ ] 默认决策路径纯规则，不调用 LLM。
- [ ] 可选模型建议关闭时，结果与当前 `decide()` 基线逐案一致。
- [ ] 写账本路径经过权限闸门登记。
- [ ] `docs_troubleshoot` 黄金集 / git-docs 不因本规格文档新增而错误失败（语料基线按仓库约定刷新）。

### 8.3 非目标指标

不将检索 MRR、开放问答满意度、Live ReAct 步数作为 expense 发布门禁。

## 9. 配置（预留）

```env
REACT_AGENT_EXPENSE_DECISION_MODEL=off
REACT_AGENT_EXPENSE_FIXTURE_DIR=
REACT_AGENT_EXPENSE_ENGINE=workflow
```

具体键名以实现 PR 为准；新增键须更新 [`DEPLOY.md`](../DEPLOY.md)。

## 10. 里程碑

| 阶段 | 交付 | 退出标准 |
|------|------|----------|
| **M0** | Fixture 收敛至 `fixtures/expense/`；规则 `decide` + ledger 评测 | 路径单一、评测绿 |
| **M1** | Workflow 包裹现有规则路径；demo/HTTP 离线切到同一编排 | §8.2 编排项打勾；基线决策一致 |
| **M2** | 决策节点输出 §6.2 形状；权限登记写路径 | 契约测试 + 闸门测试 |
| **M3** | 可选模型建议（分类/风险/例外），默认 off | 开启不影响 golden；关闭等于规则基线 |
| 之后 | 真挂起态 `escalated`、外部审批回调、多政策版本 | 另开规格修订 |

## 11. 修订规则

- 变更决策码枚举、节点表或状态机：必须改本文件并写入修订记录。
- 纯实现重构、不改对外决策语义：可只改代码与测试。
- 与 Redis 任务队列、沙箱等横切能力交叉时，以各专项规格为准。

### 修订记录

| 日期 | 说明 |
|------|------|
| 2026-10-10 | 初稿：② 主线下 Workflow + 决策模型目标态与边界 |
