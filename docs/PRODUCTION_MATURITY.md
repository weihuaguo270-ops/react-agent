# 生产成熟度

本页记录企业内部智能工作助手（work-assistant）两个办公场景的工程成熟度。它是可部署、可评测的原型清单，不是生产 SLA 或多租户平台承诺。

主场景：规范咨询（docs_troubleshoot）；第二场景：报销办理（expense）。
`change-delivery`（受控变更交付）已独立且已停止，不再作为本仓业务线；本仓已移除其文档附录与运行入口。
非目标：生产 SaaS、多租户平台、长期线上 SLA、自动根因诊断、云 APM。

## 能力状态

| 能力 | 状态 | 说明 |
|---|---|---|
| 离线 Agent 循环 | 已具备 | agent_runner 记录观测、工具选择和轨迹 |
| ReAct + Tool Calling | 已具备 | react_loop，可按配置接入模型 |
| 规范咨询 | 已具备 | 引用校验、无依据拒答、现场 evidence、HTTP/Docker 入口 |
| 报销办理 | 已具备原型 | 政策决策、表单约束、`route_review` / `resolve_review` 复核闭环、版本与决策指纹校验、审批审计和轨迹回放；当前为进程内原型存储，不承诺生产 SLA |
| 权限闸门 | 已具备 | deny → ask → allow，副作用可进入人工审批 |
| Format B 轨迹与 StepWatcher | 已具备 | 供回归与质量配件消费 |
| 黄金集与离线评测 | 已具备 | 作为原型验收证据和验收附录，不作为产品卖点，也不升格为生产成熟度 |
| HTTP 服务与 Docker 单实例 | 已具备 | 适合原型部署和复现 |
| 「3 个项目、30 条真实任务、10 条独立 held-out」 | 已放弃 | 不再作为发布门槛或下一阶段必做事；不为 llm-eval-engine 与 trace-debugger 补齐跨仓账本 golden 或 held-out |
| 多租户 / 长期 SLA | 本阶段不做 | 不对外承诺 |

## 主产品闭环

~~~
员工请求
  → 规范咨询或报销办理
  → 权限 / 人工审批 / 业务终态
  → Format B 轨迹与验收证据
~~~

质量闭环由独立仓库完成：

~~~
工作助手产出轨迹
  → trace-debugger：失败打标、scan/compare、CI
  → llm-eval-engine：过程/业务证据与 pass/review/hold
~~~

## 证据边界

- 当前证据包含合成任务、离线评测和 external_real_sandbox。
- external_real_sandbox 证明真实 GitHub 写入和 PR 生命周期演练，不证明生产用户、线上容量或企业权限体系。
- κ、黄金集数量、模型比较和失败门属于验收附录，不应作为主标题。
- 2026-11-16 已放弃「3 个项目、30 条真实任务、10 条独立 held-out」发布门槛。跨仓账本 golden 仍为 0 等历史计数保留为记录。现有黄金集、故障/生产盲测和轨迹闭环继续作为原型证据。S0–S8 报销原型验收已收口。这些证据保持工程原型口径，不写成生产成熟度。

## 进一步阅读

- 应用方向：docs/features/application-direction.md
- 当前状态：docs/STATUS.md
