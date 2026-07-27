# 生产网关超时（504）

API 网关返回 **HTTP 504 Gateway Timeout** 时，表示上游服务在网关等待窗口内未响应。

排查顺序（只读）：

1. 查日志关键字 `upstream_timeout` 与 `trace_id`
2. 确认上游 `/health` 是否可用
3. 核对 `REACT_AGENT_TOOL_TIMEOUT` 与网关超时是否一致（默认 30s）

**不要**在未确认上游状态前重启生产实例。
