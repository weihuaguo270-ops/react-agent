# Development v5 Protocol Optimization

本轮针对 v4 暴露的上下文膨胀和缺少提交终态进行代码级修正，未启动新的模型调用。

变更：

- API 请求只保留最近 4 组 assistant/tool 交互；更早的 shell 输出由本地摘要压缩。
- 完整原始消息、请求和响应继续写入每条运行目录，不影响审计。
- 增加 `submit` 工具。Agent 完成最小修复并通过聚焦测试后必须立即提交；提交后直接执行隐藏验收。
- `shell` 输出上限保持受控，避免单次工具结果扩大上下文。
- 修正预算护栏为 `budget - guard - usage`，provider `usage.total_tokens` 仍是唯一计量来源。
- 保留 `max_turns`、`max_seconds` 和单次 completion 上限。

验证：

- `python -m py_compile scripts/run_blind_pilot.py` 通过。
- `compact_messages` 最小调用通过。
- v1 至 v4 原始结果不变；held-out 不运行。

下一次只允许运行一条 development 任务，建议使用 `BLIND_TASK_IDS=httpx-activity-review` 作为低风险回归，因为此前该任务已证明可以形成正确补丁。该次结果用于验证提交终态和上下文压缩，不能与 v4 结果直接合并计算。
