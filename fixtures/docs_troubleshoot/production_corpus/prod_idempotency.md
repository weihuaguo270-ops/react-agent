# 生产幂等（Idempotency）

写操作（POST 创建资源）在生产环境**必须**携带请求头：

```
Idempotency-Key: <client-generated-uuid>
```

缺少 `Idempotency-Key` 时，网关返回 HTTP **409 Conflict**，错误码 `missing_idempotency_key`。

重复提交相同 Key 时返回首次结果，不会重复创建。
