# API 端点与速率限制

速率限制：默认每密钥 60 次/分钟；超限返回 HTTP `429`，错误码 `rate_limited`。

### POST /v1/chat

请求体：

```json
{
  "message": "用户问题",
  "session_id": "可选会话 id"
}
```

成功响应含 `request_id` / `answer` / `citations`。
