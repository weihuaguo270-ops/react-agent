# 企业内部工作助手（work-assistant）

`react-agent` 是企业内部工作助手的过渡仓库：面向需要查规范、处理报销的员工，提供受控 Agent 执行、引用证据、人工审批边界和完整轨迹。仓库名暂保留为 `react-agent`，对外产品叙事以 **work-assistant** 为准。

## 一句话定位

企业内部工作助手帮助员工完成两件办公事：**规范咨询**（`docs_troubleshoot`）和**报销办理**（`expense`）。运行时、权限闸门、轨迹和评测是实现这些应用的工程能力，不是单独对外销售的通用 Agent 框架。

## 做什么 / 不做什么

| 做什么 | 不做什么 |
|---|---|
| 依据内部文档回答规范问题，缺少证据时拒答或转人工 | 不宣称生产 SaaS、企业多租户或长期线上 SLA |
| 按政策和表单约束办理报销，保留决策与审批证据 | 不把合成任务、离线指标或沙箱成功率写成生产业务成功率 |
| 受控调用工具、记录 Format B 轨迹、支持回归验收 | 不把仓库包装成通用 Agent 平台、自动根因诊断或云 APM |

当前证据是可部署、可评测的工程原型，包含合成任务与 `external_real_sandbox`。GitHub 写入和 PR 生命周期在沙箱中是真实演练，但不代表生产用户、真实流量或企业权限体系已经接入。

## 两个办公场景

### 规范咨询（主场景）

员工询问内部 API、部署、故障排查或操作规范。助手检索文档、校验引用、组织证据化回答；没有足够依据时拒答。入口与评测：

```bash
set REACT_AGENT_APP=docs_troubleshoot
set REACT_AGENT_RAG_MODE=keyword
python demos/demo_docs_troubleshoot.py
python scripts/eval/docs/run_docs_troubleshoot_eval.py
python -m react_agent.server --port 8765
```

演示闭环是：员工提问 → 检索规范 → 带引用回答或无依据拒答 → 说明权限/审批边界 → 落盘并回放轨迹。只读规范咨询不触发人工审批；涉及副作用的修复步骤仍由 `permission_gate` / approval 控制。

### 报销办理（第二场景）

员工提交报销信息，助手按政策和表单约束完成校验，必要时由 `route_review` 分拣到人工复核，再由通过权限闸门且绑定单据版本与 `decision_hash` 的 `resolve_review` 完成批准、拒绝或升级，同时落盘审批审计和可回放轨迹。当前是可部署工程原型，不代表生产 SLA。入口与评测：

```bash
python demos/demo_expense_workflow.py
python scripts/eval/acceptance/run_expense_business_eval.py --split dev
```

独立申请人表单与运营台由 FastAPI 提供：配置现有 `REACT_AGENT_DATABASE_URL`（处理人另配 `REACT_AGENT_EXPENSE_CASE_ACTORS_FILE`）后运行 `react-agent-api --host 127.0.0.1 --port 8765`。浏览器打开 `http://127.0.0.1:8765/expense` 可保存草稿、提交、刷新审批结果与同一单工单时间线；打开 `/expense/ops` 可查看有权待审队列并认领/转派/绑定审批结案。S7 已完成，证据见 [第一刀](docs/specs/expense/evidence/s7-claim-form.md) 与 [运营视图](docs/specs/expense/evidence/s7-ops-views.md)。

两条场景属于同一员工工作助手，不是两个并列产品。底层 `react_loop`、`agent_runner`、ToolGuard、Harness 和服务入口由两个场景复用。

## 受控变更交付：规划中的独立项目

原 GitHub 交付能力将独立命名为 **受控变更交付（`change-delivery`）**。它负责读取 Issue、影子执行、隔离测试，并在人工审批后创建 Draft PR。当前阶段只保留在文档中，不拆 Git 仓库、不迁移代码、不与两个主场景并列宣传。

详见 [`docs/change-delivery-plan.md`](docs/change-delivery-plan.md) 和技术附录 [`docs/features/github-delivery-workflow.md`](docs/features/github-delivery-workflow.md)。

## 跨仓质量闭环

工作助手或未来的 `change-delivery` 产出轨迹后，质量配件按固定顺序消费：

```text
工作助手或受控变更交付产出轨迹
  → trace-debugger：规则失败打标、scan/compare、CI
  → llm-eval-engine：过程/业务证据与失败门，输出 pass/review/hold
```

- [`trace-debugger`](https://github.com/weihuaguo270-ops/trace-debugger)：轨迹失败雷达与 CI 钩子，提供便宜、可解释、可回归的失败证据，不做最终发版裁决。
- [`llm-eval-engine`](https://github.com/weihuaguo270-ops/llm-eval-engine)：发版前自检，汇总过程、业务、失败门和性能证据，输出 `pass` / `review` / `hold`。
- 两个质量仓保持独立，也可被 `change-delivery` 编排进 CI；不会合并成一个交付仓。

共享轨迹契约见 [`schemas/harness_trajectory.schema.json`](schemas/harness_trajectory.schema.json)。

## 运行与验收入口

```bash
# 本地 Agent 冒烟
python -m react_agent "用 calculator 算 17*19"

# 规范咨询
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
| 企业内部工作助手 / `work-assistant` | 对外主产品 | 规范咨询 + 报销办理 |
| 受控变更交付 / `change-delivery` | 规划中的独立产品 | Issue → 影子执行 → 人工审批 → Draft PR |
| `trace-debugger` | 质量配件 | 失败信号、规则回归、CI，不做最终裁决 |
| `llm-eval-engine` | 质量配件 | 发版前自检，输出 `pass/review/hold` |

## 简历项目简介

企业内部工作助手（`work-assistant`）工程原型，面向需要查内部规范、办理报销的企业员工。
规范咨询支持员工提问、检索内部文档、带引用回答；证据不足时明确拒答并保留查询轨迹。
报销办理按政策和表单约束校验，异常或高风险单据进入人工复核，由审批人批准、拒绝或升级。
副作用操作经过 `permission_gate` / approval，审批绑定单据版本与 `decision_hash`，结果写入审计记录并可回放。
底层复用 Agent runtime、轨迹和评测闭环，接入 `trace-debugger` 与 `llm-eval-engine` 做发布前验收。
当前证据来自合成任务与 `external_real_sandbox`，定位为可部署、可评测原型，不承诺生产 SaaS、多租户或长期线上 SLA。

## 演示讲法

先以员工身份提出一个内部规范问题，助手检索可引用的企业文档并返回证据化答案；找不到可靠依据时会拒答。再提交一笔报销，系统按政策和表单校验，必要时由 `route_review` 转入人工审批，审批人通过受保护的 `resolve_review` 批准、拒绝或升级。全程展示权限闸门、版本与决策指纹校验、审计记录和轨迹回放，最后说明 `trace-debugger` 负责失败扫描、`llm-eval-engine` 负责发布前 pass/review/hold，自身仍是可部署工程原型。

## 进一步阅读

- 当前状态：[`docs/STATUS.md`](docs/STATUS.md)
- 应用方向：[`docs/features/application-direction.md`](docs/features/application-direction.md)
- 变更交付计划：[`docs/change-delivery-plan.md`](docs/change-delivery-plan.md)
- 口径检查清单：[`docs/PORTFOLIO_POSITIONING_CHECKLIST.md`](docs/PORTFOLIO_POSITIONING_CHECKLIST.md)
- 架构：[`docs/architecture/core-architecture.md`](docs/architecture/core-architecture.md)
- 生产边界：[`docs/PRODUCTION_MATURITY.md`](docs/PRODUCTION_MATURITY.md)
