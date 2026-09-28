# v10 HTTPX 协议异常（2026-09-22）

`httpx-identity-review` 的 v10 运行目录为 `runs/dev-v10-httpx-identity-20260922-122056`（具体时间以目录为准）。在终态阶段请求只开放 `submit` 并设置强制 tool choice，但兼容服务返回了单个 `shell` 调用。v10 主机侧完整批次校验立即停止，记录 `protocol_violation`，没有执行该 shell。

证据：`protocol-violation.json` 保存违规批次，`model-18.json` 保存原始服务响应，`result.json` 记录 `protocol_violation`、52582 tokens 和 budget compliant，`acceptance/result.json` 为 passed，`patch.diff` 与完整 conversation 也已保存。

这不是运行器误判，而是服务没有遵守终态工具约束。hidden 通过只表示工作树已有补丁通过验收，不能把该次运行计为正常终态或主动 submit。按协议，剩余 development 任务暂停，待兼容服务能稳定遵守终态 `submit` 约束后再继续。
