# 受控变更交付（change-delivery）独立计划

## 产品名与定位

受控变更交付（change-delivery）面向需要把 Issue 或任务单转成受控代码变更的团队。它是工作助手之外的独立产品计划，不是规范咨询或报销办理的第三个场景。

## 职责边界

~~~
Issue / 任务单
  → 读取与计划
  → 隔离工作区影子执行
  → 测试与失败回归
  → 人工审批
  → Draft PR
~~~

它负责任务编排、隔离执行、计划指纹、审批绑定、候选提交和 PR 状态；外部写入必须显式授权。

## 复用 react-agent 的能力

- 复用 Agent 循环、ToolGuard、权限判定、轨迹契约、Harness、任务验收和审批接口。
- 不复制权限、轨迹和审批实现；未来独立产品通过稳定接口或共享包调用。
- 当前代码仍在 react-agent，本阶段不新建仓库、不迁移实现。

## Go 后端后置条件

只有在 webhook 来源与鉴权边界冻结、任务队列与幂等键确定、Episode/Artifact/PR 状态持久化方案确定，并且已有真实业务责任人和回滚流程后，才考虑 Go 服务。

Go 后端的候选职责是 webhook、鉴权、任务队列、状态持久化和 PR 状态同步，不重写现有 Agent 循环。

## CI 编排关系

~~~
工作助手或 change-delivery 产出轨迹
  → trace-debugger：规则失败打标、scan/compare、CI
  → llm-eval-engine：过程/业务证据与失败门
  → pass / review / hold
~~~

trace-debugger 负责便宜、确定性的失败信号；llm-eval-engine 负责汇总证据和最终 pass/review/hold。两个质量仓保持独立，均可被交付线编排进 CI。

## 当前状态

本页是规划和边界说明。现有 GitHub 交付实现详见 features/github-delivery-workflow.md，沙箱证据仍标记为 external_real_sandbox，不等同生产系统。
