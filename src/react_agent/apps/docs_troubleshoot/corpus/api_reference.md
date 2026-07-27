# Agent Runtime API 参考

## 认证

所有 `/v1/*` 请求须带请求头：

```
Authorization: Bearer <API_KEY>
X-Request-Id: <uuid>
```

缺少 `Authorization` 时返回 `401`，错误体：

```json
{"error":{"code":"unauthorized","message":"missing bearer token","request_id":"..."}}
```

## 端点

### GET /health

返回服务状态。无需鉴权。

```json
{"status":"ok","version":"0.2.0","app":"docs_troubleshoot"}
```

### POST /v1/chat

请求体：

```json
{
  "message": "用户问题",
  "session_id": "可选会话 id"
}
```

成功响应：

```json
{
  "request_id": "uuid",
  "answer": "带引用的回答",
  "trajectory_id": "traj-...",
  "citations": [{"source":"api_reference.md","snippet":"..."}]
}
```

速率限制：默认每密钥 60 次/分钟；超限返回 `429`，`code=rate_limited`。

## 错误码

| code | HTTP | 含义 |
|------|------|------|
| unauthorized | 401 | 缺/错 API Key |
| rate_limited | 429 | 超速率 |
| invalid_request | 400 | 请求体非法 |
| not_found | 404 | 资源不存在 |
| internal_error | 500 | 未分类内部错误 |
