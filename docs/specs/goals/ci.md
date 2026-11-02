# CI Goal

唯一进度源：`progress_source: docs/specs/ci/progress.yaml`。

CI 是 AI Review 总流程的确定性执行子系统，负责当前 diff 的规则选择、PR readiness、受影响检查、stage gate、安全确定性检查和合并输入聚合。它不定义 AI findings、人工审批、Harness/Evaluation 评分或发布观察。

定向阅读：

- [CI 子系统 Spec](../ci/spec.md)
- [CI 迁移计划](../ci/redesign-plan.md)
- [CI Registry v2](../ci/registry-v2.json)
- [CI Registry v2 schema](../ci/registry-v2.schema.json)
