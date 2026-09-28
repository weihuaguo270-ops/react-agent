# v10 development 复测汇总（2026-09-22）

| 任务 | 终态 | hidden | tokens | 说明 |
| --- | --- | --- | ---: | --- |
| pydantic-identity-review | terminal_submitted | passed | 51140 | 合法 submit，协议正常。 |
| httpx-identity-review | terminal_submitted | passed | 53473 | `tool_choice: required` 后协议正常。 |
| httpx-activity-review | terminal_submitted | passed | 53369 | 协议正常。 |
| werkzeug-auth-whitespace-3129 | protocol_violation | failed | 50852 | 终态仍返回 shell，运行器拦截；hidden 未通过。 |

HTTPX identity 的 required-tool 重测证明兼容参数在该次请求有效，但 Werkzeug 再次出现同类异常，说明服务端工具选择遵循尚未稳定，不能宣布 v10 development 全量闭环。所有违规 shell 均未执行，原始响应和 `protocol-violation.json` 已保存。

统计冻结：v6 仍是正式可比基线；v7/v8/v9 为校准；v10 为协议修复验证。`terminal_submitted`、`protocol_violation`、`budget_exhausted` 不计主动提交。Click/Jinja held-out 未运行，golden 仍为 0。剩余工作是先解决兼容服务工具选择稳定性，再重跑 Werkzeug；不继续消耗 held-out 预算。
