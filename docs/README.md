# 工作助手文档导航

本仓库与英文工作名统一为 work-assistant，中文名为企业内部智能工作助手；主场景是规范咨询，第二场景是报销办理。Python 包、命令和环境变量保持原有兼容名称。

## 快速入口

- 项目首页：../README.md
- 当前状态：STATUS.md
- 应用方向：features/application-direction.md
- 对外口径检查：PORTFOLIO_POSITIONING_CHECKLIST.md

## 按主题

### 应用与部署

- features/application-direction.md：两个办公场景和边界
- features/evidence-docs-troubleshoot.md：规范咨询实现说明
- features/deploy.md：原型部署
- change-delivery-plan.md、features/github-delivery-workflow.md：历史附录（`change-delivery` 已独立且已停止，不再作为本仓业务线）

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
工作助手产出轨迹
  → trace-debugger：失败打标、scan/compare、CI
  → llm-eval-engine：过程/业务证据与 pass/review/hold
~~~

历史报告、快照和 archive 目录保留为证据，不改变当前产品命名。
