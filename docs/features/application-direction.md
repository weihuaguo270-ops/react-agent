# 应用方向：企业内部工作助手

本仓库的对外产品名为 **企业内部工作助手（work-assistant）**。它服务同一员工身份下的两件办公事，而不是三条并列业务线或通用 Agent 框架。

| 场景 | 业务问题 | 入口 | 证据重点 |
|---|---|---|---|
| **规范咨询**（主场景） | 员工查内部规范、API、部署和故障排查信息 | docs_troubleshoot、python -m react_agent.server | 检索、引用校验、无依据拒答、现场证据 |
| **报销办理**（第二场景） | 员工提交报销并按政策完成校验，必要时进入人工复核闸门 | expense、demos/demo_expense_workflow.py | 表单约束、政策决策、`needs_review`、决策审计和轨迹回放 |

## 应用做什么

- 让员工用自然语言完成规范查询和报销办理。
- 通过工具权限、人工审批和轨迹记录控制副作用。
- 将结果、引用、审批和失败证据交给质量闭环复核。

## 规范咨询演示闭环

主场景的可运行演示由 `run_docs_agent()` 驱动：员工提问后先检索内部规范，再经过引用校验，输出带引用回答或明确拒答；只读咨询无需人工审批，涉及副作用的修复步骤仍受 `permission_gate` / approval 控制，最终轨迹会落盘并可用 Harness replay 回放。

```bash
python demos/demo_docs_troubleshoot.py
```

规范咨询当前保留离线验收集、故障模拟和 Git 文档 held-out 评测入口；验收附录记录的历史规模（34 条）只用于验收，不是生产质量承诺。

## 报销办理演示闭环

第二场景由 `expense_claim_review@1` 驱动：政策检索 → 结构化表单校验 → 规则决策 → `route_review` 分拣 → 必要时进入 `resolve_review` 人工复核 → 审计记录 → 轨迹落盘与 Harness replay。演示入口为 `python demos/demo_expense_workflow.py`。`route_review` 不得直接批准；只有绑定 `claim_id`、版本和 `decision_hash` 且通过权限闸门的 `resolve_review` 才能进入 `approved` / `rejected`，`escalate` 保持非终态。HTTP 入口为 `POST /v1/expense/reviews/{approval_id}/resolve`；通用 `/v1/approvals` 仅兼容 CONFIRM 凭据。

## 应用不做什么

- 不把运行时包装成通用 Agent 平台或独立评测 SaaS。
- 不宣称生产多租户、长期线上 SLA、自动根因诊断或云 APM。
- 不把离线验收数据、κ、模型榜或沙箱成功率写成生产业务指标。

## 规划中的独立产品

原 GitHub 交付线命名为 **受控变更交付（change-delivery）**。它会读取 Issue、影子执行、隔离测试，在人工审批后创建 Draft PR。当前阶段只在文档中独立规划，代码仍留在本仓，不与规范咨询、报销办理并列为主产品场景。

计划页：docs/change-delivery-plan.md。现有实现说明：docs/features/github-delivery-workflow.md。

## 跨仓质量配件

~~~
工作助手或受控变更交付产出轨迹
  → trace-debugger：规则失败打标、scan/compare、CI
  → llm-eval-engine：过程/业务证据与失败门，输出 pass/review/hold
~~~

| 仓库 | 角色 | 明确边界 |
|---|---|---|
| trace-debugger | 轨迹失败雷达与 CI 钩子 | 不做最终发版裁决 |
| llm-eval-engine | 发版前自检 | 不负责 Agent 运行时 |

两个质量仓保持独立，也可被 change-delivery 编排进 CI；不会合并成一个交付仓。

## 项目命名与边界

| 中文名 | 英文工作名 | 当前状态 |
|---|---|---|
| 企业内部工作助手 | work-assistant | 主产品，规范咨询 + 报销办理 |
| 受控变更交付 | change-delivery | 规划中的独立产品，暂不拆仓 |
| 轨迹失败雷达与 CI 钩子 | trace-debugger | 独立质量配件 |
| 发版前自检 | llm-eval-engine | 独立质量配件 |

## 简历项目简介

企业内部工作助手（work-assistant）工程原型，面向需要查内部规范、办理报销的企业员工。
规范咨询支持员工提问、检索内部文档、带引用回答；证据不足时明确拒答并保留查询轨迹。
报销办理按政策和表单约束校验，异常或高风险单据进入人工复核，由审批人批准、拒绝或升级。
副作用操作经过 permission_gate / approval，审批绑定单据版本与 decision_hash，结果写入审计记录并可回放。
底层复用 Agent runtime、轨迹和评测闭环，接入 trace-debugger 与 llm-eval-engine 做发布前验收。
当前证据来自合成任务与 external_real_sandbox，定位为可部署、可评测原型，不承诺生产 SaaS、多租户或长期线上 SLA。

## 演示讲法

先以员工身份提出一个内部规范问题，助手检索可引用的企业文档并返回证据化答案；找不到可靠依据时会拒答。再提交一笔报销，系统按政策和表单校验，必要时由 `route_review` 转入人工审批，审批人通过受保护的 `resolve_review` 批准、拒绝或升级。全程展示权限闸门、版本与决策指纹校验、审计记录和轨迹回放，最后说明 `trace-debugger` 负责失败扫描、`llm-eval-engine` 负责发布前 pass/review/hold，自身仍是可部署工程原型。

## 运行入口

~~~
# 规范咨询
set REACT_AGENT_APP=docs_troubleshoot
python scripts/eval/docs/run_docs_troubleshoot_eval.py

# 报销办理
python demos/demo_expense_workflow.py
python scripts/eval/acceptance/run_expense_business_eval.py --split dev
~~~
