# 贡献指南（Contributing）

感谢关注本仓库。这是个人维护的 **生产向 Agent 运行时原型**（可服务化、可回归；非多租户平台），欢迎 Issue 与小范围 PR。

仓库怎么读：[`docs/STRUCTURE.md`](docs/STRUCTURE.md)。

## 开发环境

```bash
pip install -e ".[test]"           # 核心 + pytest/flake8
pip install -e ".[rag,test]"       # 需要语义记忆 / RAG 时
pytest tests/ -q
```

可选本机 MCP：复制 `mcp_servers.example.json` → `mcp_servers.json`（已 gitignore，勿提交绝对路径）。

## 提交约定

- 使用简明的 commit message（`feat:` / `fix:` / `docs:` / `test:` / `ci:`）
- PR 请说明：改了什么、为什么改、如何验证
- 不要提交 `.env`、API Key、本地轨迹/密钥配置、`mcp_servers.json`

## 范围说明

大规模功能重构或与「可复现原型 / 非生产平台」定位冲突的改动，请先开 Issue 讨论。
权限 / 子进程执行 **不是** 生产安全边界，相关 PR 请勿按「加固沙箱产品」宣传。
