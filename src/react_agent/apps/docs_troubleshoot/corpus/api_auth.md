# API 认证

所有 `/v1/*` 请求须带请求头：

```
Authorization: Bearer <API_KEY>
X-Request-Id: <uuid>
```

缺少 `Authorization` 或缺 Bearer Token 时返回 HTTP `401`，错误体：

```json
{"error":{"code":"unauthorized","message":"missing bearer token","request_id":"..."}}
```
