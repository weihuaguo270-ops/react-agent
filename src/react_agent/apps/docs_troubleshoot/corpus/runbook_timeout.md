# 工具超时与 ToolGuard

工具调用由 ToolGuard 包裹，默认超时 **30 秒**。可通过环境变量调整：

```
REACT_AGENT_TOOL_TIMEOUT=30
```

超时后返回 `tool_timeout` 观测，主循环可重试或换工具；子进程沙箱与 ToolGuard 独立配置。
