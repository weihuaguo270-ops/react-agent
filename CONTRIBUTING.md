# 贡献指南

ReAct Agent 是个人维护的 Agent 运行时原型：可服务化、可回归；非多租户平台。欢迎 Issue 与小范围 PR。

仓库结构：[`docs/STRUCTURE.md`](docs/STRUCTURE.md)。

## 开发环境

```bash
pip install -e ".[test]"           # 核心 + pytest/flake8
pip install -e ".[rag,test]"       # 需要语义记忆 / RAG 时
pytest tests/ -q
```

可选本机 MCP：复制 `mcp_servers.example.json` → `mcp_servers.json`（已 gitignore，勿提交绝对路径）。

## 提交约定

- commit message 格式：`feat:` / `fix:` / `docs:` / `test:` / `ci:`
- PR 说明：改动内容、原因、验证方式
- 勿提交 `.env`、API Key、本地轨迹/密钥配置、`mcp_servers.json`

## 范围

与「可复现原型 / 非生产平台」定位冲突的大规模重构，请先开 Issue。  
权限与子进程执行为运行时防护，不是生产级沙箱产品；相关 PR 请按实际能力描述。
