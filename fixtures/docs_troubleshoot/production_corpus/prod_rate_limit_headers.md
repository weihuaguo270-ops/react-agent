# 生产速率限制响应头

触发限流时除 HTTP **429** 与 `rate_limited` 外，响应头应包含：

```
Retry-After: 60
```

客户端须读取 `Retry-After`（秒）后再退避重试；不得忽略该头硬冲。
