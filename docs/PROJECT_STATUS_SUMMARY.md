# 项目当前状态总结

## 项目定位

react-agent 是企业内部工作助手（work-assistant）的工程原型，面向同一员工身份下的规范咨询和报销办理。

可以表述为可部署、可评测的 Agent 应用原型；不能表述为生产 SaaS、长期线上 SLA、企业多租户权限平台或自动根因诊断系统。

## 当前闭环

| 部分 | 状态 |
|---|---|
| 规范咨询 | 已有文档检索、引用校验、拒答策略、现场证据和离线评测入口 |
| 报销办理 | 已有政策决策、表单约束、`route_review` / `resolve_review` 复核闭环、版本与决策指纹校验、审批审计和轨迹回放原型；正式业务持久化仍待 PostgreSQL 阶段 |
| 受控变更交付 | 规划中的独立产品；现有 GitHub 流程仍作为技术附录保留 |
| 轨迹与质量 | Format B、Harness、trace-debugger 失败扫描和 llm-eval-engine 发布前自检已形成跨仓闭环 |
| 生产成熟度 | held-out/golden 和真实业务接入仍有缺口，不能宣称生产成熟度 |

## 证据边界

- 当前证据包括合成任务、离线评测和 external_real_sandbox。
- 沙箱中的真实 GitHub 写入、Draft PR、接受/拒绝和回滚演练不等于生产用户流量。
- κ、黄金集数量、模型选型榜和失败门属于验收附录，不是产品主标题。

## 跨仓职责

~~~
工作助手或 change-delivery 产出轨迹
  → trace-debugger：失败打标、scan/compare、CI
  → llm-eval-engine：过程/业务证据与 pass/review/hold
~~~

## 仍需补齐

- 真实业务责任人、长期运行和人工效率基线；
- 多租户、企业权限、线上告警和回滚体系；
- change-delivery 的独立服务边界与后端部署条件。
