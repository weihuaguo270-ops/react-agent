# Development v5 Full Run

更正（2026-09-20）：四条均为预算护栏终止，submit 为 0/4。旧 passed 字段是隐藏验收覆盖停止原因的结果；隐藏验收 2/4 仍成立。Pydantic 补丁为 906 字节且验收失败，HTTPX identity 补丁为空。详见 [终止原因审计](V5_TERMINATION_AUDIT.md)。

v5 development 全量由 4 条任务组成：本报告汇总此前单条 `httpx-activity-review` 回归和本轮剩余 3 条补跑。held-out provisional 未运行。

| task | status | tokens | hidden | patch |
|---|---|---:|---|---|
| pydantic-identity-review | budget_exhausted | 61,535 | false | 以运行目录为准 |
| httpx-identity-review | budget_exhausted | 60,728 | false | 以运行目录为准 |
| werkzeug-auth-whitespace-3129 | passed | 60,568 | true | non-empty |
| httpx-activity-review | passed | 61,707 | true | non-empty |

结论：development hidden pass rate 为 `2/4`。两条通过任务均形成非空补丁并通过隐藏验收；两条未通过任务属于预算耗尽，不能进一步归因于补丁错误。该结果可作为 v5 development 实测成绩，成本仍为 `null`，因为 provider 价格未核实。Click/Jinja 仍为 `held_out_provisional`，本轮未运行。
