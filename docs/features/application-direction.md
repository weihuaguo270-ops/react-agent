# 应用方向：企业内部工作助手

本仓库的对外产品名为 **企业内部工作助手（work-assistant）**。它服务同一员工身份下的两件办公事，而不是三条并列业务线或通用 Agent 框架。

| 场景 | 业务问题 | 入口 | 证据重点 |
|---|---|---|---|
| **规范咨询**（主场景） | 员工查内部规范、API、部署和故障排查信息 | docs_troubleshoot、python -m react_agent.server | 检索、引用校验、无依据拒答、现场证据 |
| **报销办理**（第二场景） | 员工提交报销并按政策完成校验、审批和终态确认 | expense、demos/demo_expense_workflow.py | 表单约束、政策决策、人工审批、业务终态 |

## 应用做什么

- 让员工用自然语言完成规范查询和报销办理。
- 通过工具权限、人工审批和轨迹记录控制副作用。
- 将结果、引用、审批和失败证据交给质量闭环复核。

## 规范咨询演示闭环

主场景的可运行演示由 `run_docs_agent()` 驱动：员工提问后先检索内部规范，再经过引用校验，输出带引用回答或明确拒答；只读咨询无需人工审批，涉及副作用的修复步骤仍受 `permission_gate` / approval 控制，最终轨迹会落盘并可用 Harness replay 回放。

```bash
python demos/demo_docs_troubleshoot.py
```

规范咨询当前保留 34 条黄金集、故障模拟和 Git 文档 held-out 评测入口；这些数字用于验收，不是生产质量承诺。

## 应用不做什么

- 不把运行时包装成通用 Agent 平台或独立评测 SaaS。
- 不宣称生产多租户、长期线上 SLA、自动根因诊断或云 APM。
- 不把离线黄金集、κ、模型榜或沙箱成功率写成生产业务指标。

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

企业内部工作助手（work-assistant）工程原型，面向员工规范咨询与报销办理两类办公场景。
实现证据化文档问答、政策约束下的报销工作流、权限闸门、人工审批和完整 Agent 轨迹。
通过 trace-debugger 接入规则失败扫描与 CI 回归，通过 llm-eval-engine 汇总过程和业务证据并输出发布前结论。
当前在合成任务与 external_real_sandbox 中完成可复现实验，支持可部署、可评测的原型叙事。
证据不等同于生产 SaaS、多租户平台或长期线上 SLA。

## 运行入口

~~~
# 规范咨询
set REACT_AGENT_APP=docs_troubleshoot
python scripts/eval/docs/run_docs_troubleshoot_eval.py

# 报销办理
python demos/demo_expense_workflow.py
python scripts/eval/acceptance/run_expense_business_eval.py --split dev
~~~
