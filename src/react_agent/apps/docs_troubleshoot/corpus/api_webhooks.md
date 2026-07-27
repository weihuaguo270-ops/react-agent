# Webhook 回调

订阅事件后，平台向配置的 HTTPS URL 推送 JSON。请求头须校验：

```
X-Webhook-Signature: sha256=<HMAC-SHA256>
```

投递失败时**最多重试 3 次**（指数退避）。订阅 URL 被管理员禁用时返回 HTTP **410 Gone**，错误码 `webhook_disabled`。
