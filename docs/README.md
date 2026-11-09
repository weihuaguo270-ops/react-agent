# 工作助手文档导航

本仓库的对外产品名是企业内部工作助手（work-assistant），主场景是规范咨询，第二场景是报销办理。仓库名 react-agent 暂作过渡保留。

## 快速入口

- 项目首页：../README.md
- 当前状态：STATUS.md
- 应用方向：features/application-direction.md
- 受控变更交付计划：change-delivery-plan.md
- 对外口径检查：PORTFOLIO_POSITIONING_CHECKLIST.md

## 按主题

### 应用与交付

- features/application-direction.md：两个办公场景和边界
- features/evidence-docs-troubleshoot.md：规范咨询实现说明
- features/github-delivery-workflow.md：change-delivery 技术附录
- change-delivery-plan.md：独立产品规划
- features/deploy.md：原型部署

### 架构与运行时

- architecture/core-architecture.md
- architecture/agent-workflow.md
- architecture/structure.md
- features/plugins.md
- features/portability.md

### 规格、评测与验收

- specs/：Harness、Expense、任务队列等规格
- testing/frameworks/：评测框架和证据地图
- operations/：CI、失败回归和制品保留
- PRODUCTION_MATURITY.md：原型成熟度和生产边界

## 跨仓闭环

~~~
工作助手或 change-delivery 产出轨迹
  → trace-debugger：失败打标、scan/compare、CI
  → llm-eval-engine：过程/业务证据与 pass/review/hold
~~~

历史报告、快照和 archive 目录保留为证据，不改变当前产品命名。
