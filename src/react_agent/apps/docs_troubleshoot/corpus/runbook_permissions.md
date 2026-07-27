# Runbook：权限闸门拦截

若观测到 `blocked by permission gate`：

- DENY 工具默认不可执行（如 `delete_directory`）
- CONFIRM 工具在严格模式（`REACT_AGENT_STRICT_CONFIRM=1`）下无 HITL 会拦截
- 调试时可临时关闭：`REACT_AGENT_PERMISSION_GATE=0`
- 生产向部署禁止默认关闭权限闸门
