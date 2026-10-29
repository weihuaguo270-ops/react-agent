# AI Review 与变更保障

唯一进度源：`progress_source: docs/specs/ai-review/progress.yaml`。

本方向的顶层契约是 [AI Review 主 Spec](../ai-review/spec.md)。策略和机器可读契约按以下顺序定向阅读：

- [AI Review 主 Spec](../ai-review/spec.md)
- [AI Review 策略](../ai-review/ai-review-policy.md)
- [变更风险策略](../ai-review/risk-policy.md)
- [人工审批策略](../ai-review/approval-policy.md)
- [Artifact schema](../ai-review/artifact.schema.json)

## 阶段边界

- **A0：架构与契约**：冻结生命周期、角色边界、artifact schema、状态语义和 SHA 失效规则。
- **A1：离线审核**：使用固定 diff、Spec 和测试上下文生成结构化审核报告。
- **A2：PR report-only**：在当前 head SHA 上发布报告，不改变合并门禁或 Branch Protection。
- **A3：风险与审批编排**：接入 CI、Security 和人工审批要求。
- **A4：合并与合并后观察**：接入合并队列、发布观察、回滚和审计证据。

## 职责关系

AI Review 负责顶层编排和风险结论；CI 负责独立的确定性执行门禁；Security 负责安全结论；Harness/Evaluation 只提供 evidence；人工审批负责接受风险和最终裁决。AI Review 可以消费这些输出，但不会复制 CI 的测试语义或 Harness/Evaluation 的评分语义。

当前 A0 完成前，A1–A4 保持 `not_started`。A2 完成 report-only 实施前，AI Review 不加入 required checks。
