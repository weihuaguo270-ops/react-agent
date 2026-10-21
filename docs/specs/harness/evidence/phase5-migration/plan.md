# P5-2: 遗留导入迁移计划

**目标**: 将22个活跃的 `harness.schema` 导入迁移到 `harness.contracts`  
**策略**: 分阶段迁移，从测试文件开始，逐步迁移到源代码  
**优先级**: 测试 → 脚本 → 源代码

## 迁移阶段

### Phase 1: 测试文件 (优先级: 高)
测试文件的迁移风险最低，且能验证兼容性。

### Phase 2: 评估脚本 (优先级: 中)
脚本文件通常是独立运行的，影响范围较小。

### Phase 3: 源代码 (优先级: 低)
源代码迁移需要更仔细的测试验证。

## 迁移模式

### 模式 A: 简单替换
```python
# Before
from react_agent.harness import schema

# After
from react_agent.harness import contracts as schema
```

### 模式 B: 完整迁移
```python
# Before
from react_agent.harness.schema import validate_trajectory, SCHEMA_VERSION

# After
from react_agent.harness.contracts import validate_trajectory, SCHEMA_VERSION
```

### 模式 C: 使用统一入口
```python
# Before
from react_agent.harness.schema import load_and_validate

# After
from react_agent.harness.contracts import parse_trajectory
```

## 验证检查清单

每次迁移后：
- [ ] 运行文件相关的测试
- [ ] 检查无新增弃用警告
- [ ] 验证功能正常
- [ ] 提交小批次变更

## 批次计划

### Batch 1: 合约测试 (2-3个文件)
- tests/evaluation/test_harness_contracts.py
- tests/test_harness_schema.py

### Batch 2: 集成测试 (3-5个文件)
- tests/integration/test_reliability_*.py
- tests/evaluation/test_http_trajectory_contract.py

### Batch 3: 评估测试 (5-7个文件)
- tests/evaluation/test_*.py

### Batch 4: 脚本文件 (2-3个文件)
- scripts/eval/acceptance/*.py
- scripts/eval/integration/*.py

### Batch 5: 源代码 (如有)
- src/react_agent/**/*.py (如果有直接引用)

## 回滚策略

如果迁移导致问题：
1. git revert 相关提交
2. 修复问题
3. 重新尝试迁移

## 进度跟踪

| 批次 | 文件数 | 状态 | 测试 | 提交 |
|------|--------|------|------|------|
| Batch 1 | 2-3 | ⏳ 待开始 | - | - |
| Batch 2 | 3-5 | ⏳ 待开始 | - | - |
| Batch 3 | 5-7 | ⏳ 待开始 | - | - |
| Batch 4 | 2-3 | ⏳ 待开始 | - | - |
| Batch 5 | 剩余 | ⏳ 待开始 | - | - |

---

**开始时间**: 2026-10-19  
**预计完成**: 1-2 个工作日
