# Harness Contracts 迁移说明

## 新入口

新的 Runtime、Evaluation 和跨仓 Adapter 代码应从
`react_agent.harness.contracts` 导入：

```python
from react_agent.harness.contracts import (
    parse_trajectory,
    serialize_trajectory,
    validate_trajectory,
)
```

`parse_trajectory()` 接受 mapping、JSON 字符串或 JSON 文件路径，统一执行
Format B 归一化和校验。`serialize_trajectory()` 负责构造并校验输出。

## 兼容入口

`react_agent.harness.schema` 在兼容周期内继续导出
`validate_trajectory()`、`normalize_trajectory()`、`assert_valid()` 和
`load_and_validate()`。旧入口不会改变历史调用行为，但新代码不得新增对它的
直接依赖。兼容周期结束后再删除重复导出，并提升 contracts parser 的覆盖范围。

## 依赖方向

`harness.contracts` 只能依赖标准库和 Format B schema 校验实现，不能依赖
`harness.runtime`、`harness.evaluation` 或 `react_agent.eval`。依赖方向测试为：

```powershell
.venv\Scripts\python.exe -m pytest -q tests/evaluation/test_harness_contracts.py
```

完整 Phase 1 校验还应覆盖：

```powershell
.venv\Scripts\python.exe -m pytest -q `
  tests/evaluation/test_harness_contracts.py `
  tests/evaluation/test_harness_schema.py `
  tests/evaluation/test_http_trajectory_contract.py
```

历史 Format B 轨迹、held-out/golden 数据和旧导入路径不得为了迁移而改写。
