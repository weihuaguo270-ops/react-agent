# Development v3 Calibration

日期：2026-09-19

本轮只运行 `pydantic-identity-review`，用于验证预算协议，不作为 Agent 能力成绩。

- 模型：`deepseek-flash`
- 镜像：`sha256:d082dcda265ca5d4f2a383fb54e10e39f3631fe9e22602591a242d350c7105bc`
- 预算：32,000 provider-reported total tokens；单次 `max_tokens` 1,024
- 预算策略：以 provider `usage.total_tokens` 累加，并在请求前保留 6,000 token 安全余量
- 运行目录：`runs/dev-v3c-20260919-...`
- 结果：`budget_exhausted`，累计 26,082 tokens，隐藏验收未通过，`patch.diff` 为空

结论：v3 已避免 v1/v2 的预算超限，但 32k 预算和当前多轮工具协议不足以完成该任务。v1/v2 原始结果保留；held-out 不运行，development 其余 3 条也不重复消耗。
