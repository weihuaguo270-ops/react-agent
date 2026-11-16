# 项目背景与对外边界

本仓库承载企业内部智能工作助手（work-assistant）的工程原型。仓库名与英文工作名统一为 work-assistant；Python 分发名 react-agent、包名 react_agent、命令和环境变量保留兼容名称。主场景是规范咨询（docs_troubleshoot），第二场景是报销办理（expense）；两者属于同一员工工作助手。

S0–S8 已按现有证据完成原型验收，当前不新增验收切片；不改评测仓，也不由此推断生产可发布。

## 对外口径

可以表述为可部署、可评测的 Agent 应用工程原型，包含权限闸门、人工审批、轨迹记录、业务终态和跨仓质量验收。

不能表述为：

- 已在企业生产环境形成长期线上流量或 SLA；
- 生产 SaaS、多租户权限平台或自动根因诊断系统；
- 合成任务、离线评测、κ 或 external_real_sandbox 成功率等于生产业务成功率；
- trace-debugger 或 llm-eval-engine 是工作助手本身；
- change-delivery 仍是本仓业务线或跨仓闭环的默认入口。

`change-delivery`（受控变更交付）已独立且已停止，不再作为本仓业务线，也不再迁移代码。

## 跨仓闭环

~~~
工作助手产出轨迹
  → trace-debugger：失败信号与 CI 回归
  → llm-eval-engine：过程/业务证据与 pass/review/hold
~~~
