# 生产可观测性（日志与 Trace）

线上排障时，**必须**在日志中携带并检索 `trace_id` 与 `request_id`：

```
trace_id=abc123 request_id=req-9f2a level=ERROR error.code=rate_limited
```

在日志平台使用 `trace_id:"abc123"` 过滤同一请求链；`request_id` 用于与 API 错误 JSON 中的 `request_id` 字段对齐。

若日志出现 `upstream_timeout` 且 HTTP 504，优先对照网关超时 Runbook（见 `prod_gateway_timeout.md`）。
