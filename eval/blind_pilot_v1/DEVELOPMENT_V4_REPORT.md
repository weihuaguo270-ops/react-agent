# Development v4 Blind Pilot

日期：2026-09-19

本轮重新运行全部 4 条 development，held-out 未运行。

- 模型：`deepseek-flash`
- 总预算：每条 64,000 provider-reported total tokens
- 单次 completion 上限：2,048
- 安全余量：4,000
- 工具轮数上限：40
- 工具输出：stdout 3,000 字符，stderr 1,000 字符
- 镜像：`sha256:d082dcda265ca5d4f2a383fb54e10e39f3631fe9e22602591a242d350c7105bc`
- 运行目录：`runs/dev-v4-20260919-200904`

结果：

| task | 状态 | tokens | hidden | patch |
|---|---|---:|---|---:|
| pydantic-identity-review | budget_exhausted | 60,080 | false | empty |
| httpx-identity-review | budget_exhausted | 61,247 | false | empty |
| httpx-activity-review | passed | 60,147 | true | non-empty |
| werkzeug-auth-whitespace-3129 | budget_violation | 64,269 | false | non-empty |

终态修正：隐藏验收是提交结果的终端判定。`httpx-activity-review` 的隐藏验收通过，因此重分类为 `passed`，不再被同轮预算边界覆盖。其余任务仍分别是 `budget_exhausted` 或 `budget_violation`，不能计为通过。

费用仍为 `null`，因为兼容服务价格未核实。held-out Click/Jinja 继续保持未运行。
