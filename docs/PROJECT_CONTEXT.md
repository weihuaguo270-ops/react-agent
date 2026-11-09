# 项目背景与对外边界

本仓库承载企业内部工作助手（work-assistant）的工程原型。主场景是规范咨询（docs_troubleshoot），第二场景是报销办理（expense）；两者属于同一员工工作助手。

## 对外口径

可以表述为可部署、可评测的 Agent 应用工程原型，包含权限闸门、人工审批、轨迹记录、业务终态和跨仓质量验收。

不能表述为：

- 已在企业生产环境形成长期线上流量或 SLA；
- 生产 SaaS、多租户权限平台或自动根因诊断系统；
- 合成任务、离线评测、κ 或 external_real_sandbox 成功率等于生产业务成功率；
- trace-debugger 或 llm-eval-engine 是工作助手本身；
- GitHub 交付已是主产品或已完成独立拆仓。

## 跨仓闭环

~~~
工作助手或 change-delivery 产出轨迹
  → trace-debugger：失败信号与 CI 回归
  → llm-eval-engine：过程/业务证据与 pass/review/hold
~~~

change-delivery 是规划中的独立产品；当前只保留文档边界，不迁移代码。
