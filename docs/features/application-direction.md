# 应用方向：企业内部智能工作助手

本仓库的对外产品名为 **企业内部智能工作助手（work-assistant）**，仓库名与英文工作名统一为 work-assistant。它服务同一员工身份下的两件办公事，而不是并列多业务线或通用 Agent 框架。

| 场景 | 业务问题 | 入口 | 证据重点 |
|---|---|---|---|
| **个人知识库**（主场景） | 员工加入链接/PDF/文件/正文形成文档与摘要，再取回；Agent 可联网生成后保存进个人库 | docs_troubleshoot、python -m react_agent.server | 文档与摘要、合并、引用/拒答、Agent 工作区 |
| **报销办理**（第二场景） | 员工提交报销并按政策完成校验，必要时进入人工复核闸门 | expense、demos/demo_expense_workflow.py | 表单约束、政策决策、`needs_review`、决策审计和轨迹回放 |

## 应用做什么

- 让员工用自然语言完成个人知识取回和报销办理。
- 通过工具权限、人工审批和轨迹记录控制副作用。
- 将结果、引用、审批和失败证据交给质量闭环复核。

## 个人知识库演示闭环

主场景页面路径：先确认 `X-Actor-Id` →「文档工作区 + Agent」。对话接入 `react_loop` + LLM 与个人库工具；未开模型时明确提示无法灵活对话和联网生成。提问只查个人库，证据不足拒答「个人库中没有足够依据」。评测默认语料路径与页面个人库分离。当前是个人沉淀演示，不是企业制度库。

```bash
python -m react_agent.server --host 127.0.0.1 --port 8765
python demos/demo_docs_troubleshoot.py
```

个人知识库保留离线验收集、故障模拟和 Git 文档 held-out 评测入口（服务契约回归，不是页面默认库）；验收附录记录的历史规模（34 条）只用于验收，不是生产质量承诺。

## 报销办理演示闭环

第二场景由 `expense_claim_review@1` 驱动：政策检索 → 结构化表单校验 → 规则决策 → `route_review` 分拣 → 必要时进入 `resolve_review` 人工复核 → 审计记录 → 轨迹落盘与 Harness replay。演示入口为 `python demos/demo_expense_workflow.py`。`route_review` 不得直接批准；只有绑定 `claim_id`、版本和 `decision_hash` 且通过权限闸门的 `resolve_review` 才能进入 `approved` / `rejected`，`escalate` 保持非终态。HTTP 入口为 `POST /v1/expense/reviews/{approval_id}/resolve`；通用 `/v1/approvals` 仅兼容 CONFIRM 凭据。

## 应用不做什么

- 不把运行时包装成通用 Agent 平台或独立评测 SaaS。
- 不宣称生产多租户、长期线上 SLA、自动根因诊断或云 APM。
- 不把离线验收数据、κ、模型榜或沙箱成功率写成生产业务指标。

`change-delivery`（受控变更交付）已独立且已停止，不再作为本仓业务线；本仓已移除其文档附录与运行入口。

## 跨仓质量配件

~~~
工作助手产出轨迹
  → trace-debugger：规则失败打标、scan/compare、CI
  → llm-eval-engine：过程/业务证据与失败门，输出 pass/review/hold
~~~

| 仓库 | 角色 | 明确边界 |
|---|---|---|
| trace-debugger | 轨迹失败雷达与 CI 钩子 | 不做最终发版裁决 |
| llm-eval-engine | 发版前自检 | 不负责 Agent 运行时 |

两个质量仓保持独立，不会合并成一个交付仓。

2026-11-16 起，跨仓发布门槛「3 个项目、30 条真实任务、10 条独立 held-out」已放弃。trace-debugger 与 llm-eval-engine 继续作为独立质量配件。本仓不再为它们补齐跨仓账本 golden 或 held-out，也不把它们改写成简历上的第三项。个人知识库与报销办理的现有离线验收保留为原型证据。工作助手简介保持下文现有文字。S0–S8 报销原型验收已收口；放弃该门槛不把现有评测写成生产成熟度。

## 项目命名与边界

| 中文名 | 英文工作名 | 当前状态 |
|---|---|---|
| 企业内部智能工作助手 | work-assistant | 仓库名与英文工作名，个人知识库 + 报销办理 |
| 轨迹失败雷达与 CI 钩子 | trace-debugger | 独立质量配件 |
| 发版前自检 | llm-eval-engine | 独立质量配件 |

## 项目简介

企业内部智能工作助手（work-assistant）工程原型，面向需要沉淀个人资料、办理报销的企业员工。
个人知识库支持加入链接、PDF、本地文件或文本、按员工身份隔离检索、带引用回答；证据不足时明确拒答并保留查询轨迹。
报销办理按政策和表单约束校验，异常或高风险单据进入人工复核，由审批人批准、拒绝或升级。
副作用操作经过 permission_gate / approval，审批绑定单据版本与 decision_hash，结果写入审计记录并可回放。
底层复用 Agent runtime、轨迹和评测闭环，接入 trace-debugger 与 llm-eval-engine 做发布前验收。
当前证据来自合成任务与 external_real_sandbox，定位为可部署、可评测原型，不承诺生产 SaaS、多租户或长期线上 SLA。

## 演示讲法

先以员工身份加入笔记、公开链接、PDF 或本地文件，助手沉淀为文档与摘要；再提问，助手按个人库文档检索并返回带引用答案，库空或无关时拒答。再提交一笔报销，系统按政策和表单校验，必要时由 `route_review` 转入人工审批，审批人通过受保护的 `resolve_review` 批准、拒绝或升级。全程展示权限闸门、版本与决策指纹校验、审计记录和轨迹回放，最后说明 `trace-debugger` 负责失败扫描、`llm-eval-engine` 负责发布前 pass/review/hold，自身仍是可部署工程原型。

## 运行入口

~~~
# 个人知识库（评测语料 / 契约）
set REACT_AGENT_APP=docs_troubleshoot
python scripts/eval/docs/run_docs_troubleshoot_eval.py

# 报销办理
python demos/demo_expense_workflow.py
python scripts/eval/acceptance/run_expense_business_eval.py --split dev
~~~
