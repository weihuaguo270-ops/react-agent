# API 错误码表

| code | HTTP | 含义 |
|------|------|------|
| unauthorized | 401 | 缺/错 API Key 或 Bearer Token |
| rate_limited | 429 | 超速率 |
| invalid_request | 400 | 请求体非法；错误码 invalid_request 对应 HTTP 400 |
| not_found | 404 | 资源不存在 |
| internal_error | 500 | 未分类内部错误 |

注意：`invalid_request` 是 **400**，与 unauthorized / rate_limited 不同。
