# AI Review A0 验收证据

状态：Complete。

本文件记录 A0 的 schema、artifact validator、当前 `head_sha` 绑定和 fail-closed 语义验证。验收在当前主干 `e641adc7c95907a1bf55f7185c90faaa87b78829` 上完成。

- Gate 命令：`python scripts/ai_review/stage_gate.py --stage A0`
- 测试：项目 `.venv` 执行 `python -m pytest -q -p no:cacheprovider tests/test_ai_review_artifact.py`
- 结果：9 passed；仅有既有弃用和 pytest 配置警告
- Schema：`artifact.schema.json` 可加载，且包含 A0 所需的必填字段
- Fail-closed：缺失 artifact、SHA 不匹配、CI/Security blocked、未关闭 blocker/high 和低置信度 finding 均由 validator 测试覆盖
- 结构化报告：[a0-latest.json](../../../artifacts/ai-review/stage-gates/a0-latest.json)
- 报告 SHA256：`3d0740c9d77282a390ee3eeffc5fc95d165e0d1d773e6fcf1a3598ed97c6d100`

A1–A4 当前保持 `not_started`；A2 在 report-only 实施完成前不进入 required checks。
