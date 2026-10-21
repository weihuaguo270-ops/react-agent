# Harness 阶段进度

`progress.yaml` 是 Harness 阶段状态的唯一查询入口。文件使用 JSON 子集，
因此既是合法 YAML，也可以由仓库内置 Python 标准库直接读取。

每个阶段包含：

- `status`：`not_started`、`in_progress` 或 `complete`；
- `gate_command`：该阶段唯一门禁命令；
- `acceptance`：验收项、证据路径和完成状态；
- `last_gate`：最近一次命令结果、报告路径和报告 SHA256。

运行阶段门禁：

```powershell
python scripts/ci/harness_stage_gate.py --stage P2
```

门禁会运行该阶段的固定测试集合，检查验收项和 `required_evidence` 的路径及
JSON 断言，生成 `artifacts/harness/stage-gates/<stage>-latest.json`，并自动回写
`progress.yaml`。退出码为 0 且所有验收项、证据均通过时，阶段才会标为
`complete`；否则保持 `in_progress`。

在受限 Windows 工作区，门禁会启用项目已有的
`REACT_AGENT_PERMISSIVE_TEST_DIRS=1` 测试目录策略，避免接管其他身份创建的
pytest 临时目录。

阶段内完成代码、测试或证据后，必须先更新 `progress.yaml` 中对应验收项和
证据路径，再运行该阶段门禁。阶段切换只需要人工确认一次；阶段内进度查询
只读取 `progress.yaml` 和其中 `last_gate` 指向的报告。
