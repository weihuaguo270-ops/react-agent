# Development v5 Regression

更正（2026-09-20）：本轮并未调用 submit，实际由预算护栏停止，随后隐藏验收通过。下文关于及时提交已验证有效的结论撤回，以 [终止原因审计](V5_TERMINATION_AUDIT.md) 为准。

本轮只运行 `httpx-activity-review`，用于验证 v5 协议优化，不与 v1-v4 批次合并计算。

| task | status | tokens | hidden | patch |
|---|---|---:|---|---:|
| httpx-activity-review | passed | 61,707 | true | non-empty |

- 模型：`deepseek-flash`
- 镜像：`sha256:d082dcda265ca5d4f2a383fb54e10e39f3631fe9e22602591a242d350c7105bc`
- 运行目录：`runs/dev-v5-20260919-...`
- 耗时：约 40 秒
- 成本：`null`，provider 价格未核实

结论：上下文压缩和显式 `submit` 终态使此前已知可解任务在隐藏验收通过后及时结束，未出现继续探索导致的预算耗尽。该结果证明协议修正有效，但不代表 4 条 development 的整体通过率，也不改变 held-out provisional 状态。
