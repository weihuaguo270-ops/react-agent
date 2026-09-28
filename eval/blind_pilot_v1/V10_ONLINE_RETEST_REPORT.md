# v10 在线复测报告（2026-09-22）

仅运行 `pydantic-identity-review`，未运行 Click/Jinja held-out。

| 项目 | 结果 |
| --- | --- |
| run | `dev-v10-pydantic-protocol-check-20260922-121512` |
| termination | `terminal_submitted` |
| hidden | passed |
| tokens | 51140 |
| budget compliant | true |
| model tool calls | shell 25, submit 1 |
| protocol violation | 未触发 |

普通阶段执行了 25 次 `shell`，终态阶段执行了 1 次合法 `submit`。没有出现终态返回 shell、混合工具、空调用或未知工具，因此没有生成 `protocol-violation.json`；该文件只在违规路径生成。patch、原始模型响应、请求、conversation、submission、patch.diff 和 hidden acceptance/result.json 均存在。

统计口径冻结：v6 是正式可比 development 基线；v7/v8/v9 是校准记录；v10 是协议修复验证，不与旧成绩合并。`terminal_submitted`、`protocol_violation`、`budget_exhausted` 均不计为主动提交。Click/Jinja held-out 继续保持未运行，golden 仍为 0。
