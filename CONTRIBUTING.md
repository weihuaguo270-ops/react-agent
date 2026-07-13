# 贡献指南（Contributing）

感谢关注本仓库。这是个人**学习 / 实验**项目，欢迎 Issue 与小范围 PR。

## 开发环境

```bash
pip install -e ".[test]"   # 若无 test extra，则: pip install -e . && pip install pytest flake8
pytest tests/ -q
```

## 提交约定

- 使用简明的 commit message（`feat:` / `fix:` / `docs:` / `test:` / `ci:`）
- PR 请说明：改了什么、为什么改、如何验证
- 不要提交 `.env`、API Key、本地轨迹/密钥配置

## 范围说明

大规模功能重构或与「学习实现」定位冲突的改动，请先开 Issue 讨论。
