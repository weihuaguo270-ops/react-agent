# API 分页

列表接口 `GET /v1/items` 支持 cursor 分页：

| 参数 | 说明 |
|------|------|
| `cursor` |  opaque 游标；非法或过期 cursor 返回 HTTP **400**，错误码 `invalid_request` |
| `limit` | 每页条数，**默认 20**，**最大 100** |

响应体含 `next_cursor`；无更多数据时 `next_cursor` 为空字符串。
