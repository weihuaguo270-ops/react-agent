# Runbook：权限闸门拦截

调试时可临时关闭：设 `REACT_AGENT_PERMISSION_GATE=0`。
生产向部署禁止默认关闭权限闸门；生产不能默认关。

若观测到 `blocked by permission gate` / `approval_required` / `blocked by strict confirm`：

- DENY 工具默认不可执行（如 `delete_directory`）
- CONFIRM / CONFIRM_READ 确认族分两档：
  - `CONFIRM_READ`（如 `read_config_snapshot`、`probe_service_health`）：闸门直接放行
  - `CONFIRM`（副作用，如 `execute_python`、`apply_fix_step`）：默认 `async` 下落盘待批，经 `/v1/approvals` 批准后重试
- CONFIRM 工具在严格模式（`REACT_AGENT_APPROVAL_MODE=auto_allow` 且 `REACT_AGENT_STRICT_CONFIRM=1`）下无 HITL 会拦截；`CONFIRM_READ` 仍放行
- 本地/CI 逃生：`REACT_AGENT_APPROVAL_MODE=auto_allow`（或 `off`）
