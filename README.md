# 企业内部智能工作助手（work-assistant）

`work-assistant` 是企业内部智能工作助手：面向需要沉淀个人资料、取回带引用答案并办理报销的员工，提供受控 Agent 执行、引用证据、人工审批边界和完整轨迹。仓库名与英文工作名统一为 **work-assistant**。

## 一句话定位

企业内部智能工作助手帮助员工完成两件办公事：**个人知识库**（`docs_troubleshoot`）和**报销办理**（`expense`）。运行时、权限闸门、轨迹和评测是实现这些应用的工程能力，不是单独对外销售的通用 Agent 框架。

## 做什么 / 不做什么

| 做什么 | 不做什么 |
|---|---|
| 把链接或文本沉淀到员工个人库，提问时只在该库检索并带引用回答；证据不足时明确拒答 | 不宣称生产 SaaS、企业制度库、多租户或长期线上 SLA |
| 按政策和表单约束办理报销，保留决策与审批证据 | 不把合成任务、离线指标或沙箱成功率写成生产业务成功率 |
| 受控调用工具、记录 Format B 轨迹、支持回归验收 | 不把仓库包装成通用 Agent 平台、自动根因诊断或云 APM |

当前证据是可部署、可评测的工程原型，包含合成任务与 `external_real_sandbox`。GitHub 写入和 PR 生命周期在沙箱中是真实演练，但不代表生产用户、真实流量或企业权限体系已经接入。

## 两个办公场景

### 个人知识库（主场景）

员工投递网页链接或文章（可附带要求），助手生成一条收藏：标题、摘要与关键词；员工可编辑后保存。之后提问时优先用关键词与来源链接检索，给出带引用的整理答案。证据不足或库为空时明确拒答，不会改用项目内置演示语料冒充个人收藏。当前是个人沉淀，不是企业制度库。

完整演示路径：

1. 启动：`python -m react_agent.server --host 127.0.0.1 --port 8765`（或已安装入口 `react-agent-api`）
2. 打开 `http://127.0.0.1:8765/`（或 `/ui`），填写 `X-Actor-Id`
3. 投递 `https` 链接和/或正文（可选要求）→ 生成可编辑收藏；同一链接再次投递会合并
4. 提问 → 按关键词 / 链接 / 标题 / 摘要检索 → 带可点击引用的答案，或「个人库中没有足够依据」拒答

成熟度：可演示原型，非生产。无模型时仍给出可编辑草稿。细粒度权限、来源合规与制度级访问控制见功能说明「后续目标」，本轮未实现；本轮唯一权限约束是按 `X-Actor-Id` 隔离入库与检索。

评测与内置 14 篇语料仍服务 golden / git_docs 等契约，与页面默认个人库路径分离：

```bash
set REACT_AGENT_APP=docs_troubleshoot
set REACT_AGENT_RAG_MODE=keyword
python demos/demo_docs_troubleshoot.py
python scripts/eval/docs/run_docs_troubleshoot_eval.py
```

### 报销办理（第二场景）

员工提交报销信息，助手按政策和表单约束完成校验，必要时由 `route_review` 分拣到人工复核，再由通过权限闸门且绑定单据版本与 `decision_hash` 的 `resolve_review` 完成批准、拒绝或升级，同时落盘审批审计和可回放轨迹。当前是可部署工程原型，不代表生产 SLA。入口与评测：

```bash
python demos/demo_expense_workflow.py
python scripts/eval/acceptance/run_expense_business_eval.py --split dev
```

独立申请人表单与运营台由 FastAPI 提供：配置现有 `REACT_AGENT_DATABASE_URL`（处理人另配 `REACT_AGENT_EXPENSE_CASE_ACTORS_FILE`）后运行 `react-agent-api --host 127.0.0.1 --port 8765`。浏览器打开 `http://127.0.0.1:8765/expense` 可保存草稿、提交、刷新审批结果与同一单工单时间线；打开 `/expense/ops` 可查看有权待审队列并认领/转派/绑定审批结案。S7 与 S8 均已完成；S8 为**原型验收 complete**，**不是生产可发布**，见 [最终汇总](docs/specs/expense/evidence/s8-final-acceptance.md)。

两条场景属于同一员工工作助手，不是两个并列产品。底层 `react_loop`、`agent_runner`、ToolGuard、Harness 和服务入口由两个场景复用。

`change-delivery`（受控变更交付）已独立且已停止，不再作为本仓业务线；本仓已移除其文档附录、demo、Skill 与专用测试入口。

## 跨仓质量闭环

工作助手产出轨迹后，质量配件按固定顺序消费：

```text
工作助手产出轨迹
  → trace-debugger：规则失败打标、scan/compare、CI
  → llm-eval-engine：过程/业务证据与失败门，输出 pass/review/hold
```

- [`trace-debugger`](https://github.com/weihuaguo270-ops/trace-debugger)：轨迹失败雷达与 CI 钩子，提供便宜、可解释、可回归的失败证据，不做最终发版裁决。
- [`llm-eval-engine`](https://github.com/weihuaguo270-ops/llm-eval-engine)：发版前自检，汇总过程、业务、失败门和性能证据，输出 `pass` / `review` / `hold`。
- 两个质量仓保持独立，不会合并成一个交付仓。

共享轨迹契约见 [`schemas/harness_trajectory.schema.json`](schemas/harness_trajectory.schema.json)。

## 运行与验收入口

```bash
# 本地 Agent 冒烟
python -m react_agent "用 calculator 算 17*19"

# 个人知识库（评测语料 / 契约）
python scripts/eval/docs/run_docs_troubleshoot_eval.py

# 报销办理
python scripts/eval/acceptance/run_expense_business_eval.py --split dev

# 跨仓闭环验收
python scripts/eval/acceptance/run_portfolio_acceptance.py
```

运行时核心在 `src/react_agent/`，应用入口在 `src/react_agent/apps/`，演示在 `demos/`，评测在 `scripts/eval/`，轨迹契约在 `schemas/`。

## 项目命名与边界

| 名称 | 角色 | 边界 |
|---|---|---|
| 企业内部智能工作助手 / `work-assistant` | 仓库名与英文工作名 | 个人知识库 + 报销办理 |
| `trace-debugger` | 质量配件 | 失败信号、规则回归、CI，不做最终裁决 |
| `llm-eval-engine` | 质量配件 | 发版前自检，输出 `pass/review/hold` |

仓库地址为 `https://github.com/weihuaguo270-ops/work-assistant`（原 `react-agent`）。Python 分发名 `react-agent`、包名 `react_agent`、`react-agent-*` 命令、`REACT_AGENT_*` 环境变量和既有 schema ID 保持兼容；本地目录可继续使用 `react-agent`。

S0–S8 已完成原型验收，后续以现有能力演示与材料整理为主，不再新增验收切片；评测仓保持独立。

跨仓发布门槛「3 个项目、30 条真实任务、10 条独立 held-out」已放弃。现有离线验收、golden/故障/生产盲测入口和轨迹质量闭环保留为原型证据。不再为 `trace-debugger` 与 `llm-eval-engine` 补齐该门槛，也不把这两个评测仓写成简历上的第三项。放弃该门槛后，工作助手仍是工程原型，现有评测不构成生产可发布。

## 简历项目简介

企业内部智能工作助手（`work-assistant`）工程原型，面向需要沉淀个人资料并办理报销的企业员工。
个人知识库支持投递链接或文本、按员工身份隔离检索、带引用回答；证据不足时明确拒答并保留查询轨迹。
报销办理按政策和表单约束校验，异常或高风险单据进入人工复核，由审批人批准、拒绝或升级。
副作用操作经过 `permission_gate` / approval，审批绑定单据版本与 `decision_hash`，结果写入审计记录并可回放。
底层复用 Agent runtime、轨迹和评测闭环，接入 `trace-debugger` 与 `llm-eval-engine` 做发布前验收。
当前证据来自合成任务与 `external_real_sandbox`，定位为可部署、可评测原型，不承诺生产 SaaS、多租户或长期线上 SLA。

## 演示讲法

先以员工身份投递笔记或公开链接（可带要求），助手生成可编辑收藏并列出标题、关键词与摘要；再提问，助手按关键词/链接检索并返回带引用答案，库空或无关时拒答。再提交一笔报销，系统按政策和表单校验，必要时由 `route_review` 转入人工审批，审批人通过受保护的 `resolve_review` 批准、拒绝或升级。全程展示权限闸门、版本与决策指纹校验、审计记录和轨迹回放，最后说明 `trace-debugger` 负责失败扫描、`llm-eval-engine` 负责发布前 pass/review/hold，自身仍是可部署工程原型。

## 进一步阅读

- 当前状态：[`docs/STATUS.md`](docs/STATUS.md)
- 应用方向：[`docs/features/application-direction.md`](docs/features/application-direction.md)
- 口径检查清单：[`docs/PORTFOLIO_POSITIONING_CHECKLIST.md`](docs/PORTFOLIO_POSITIONING_CHECKLIST.md)
- 架构：[`docs/architecture/core-architecture.md`](docs/architecture/core-architecture.md)
- 生产边界：[`docs/PRODUCTION_MATURITY.md`](docs/PRODUCTION_MATURITY.md)
