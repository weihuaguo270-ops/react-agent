# P4 实施计划 - Replay and Regression Gates

## 执行日期
2026-10-19

## 任务概述

**P4: Replay and Regression Gates**
- 状态：IN PROGRESS (0/1 complete)
- 目标：建立 baseline compare、repair/reverify 闭环和回归门禁

---

## 1. 需求分析

### P4-1 验收标准

根据 `docs/spec/goals/harness.md`:

> `P4-1` 只有在阶段门禁成功、baseline compare 报告存在、repair→reverify 真实重跑链路可追溯，且 `progress.yaml` 中的 artifact 路径和 SHA256 均有效时才能标记完成。历史、fixture 和当前执行证据必须分栏；没有真实复验的修复不能转为 pass。

### 核心要求拆解

1. **Baseline Compare 报告** ✅ 部分存在
   - 比较历史基线和当前执行
   - 输出差异分析
   - 当前状态：有历史证据，缺少比较报告

2. **Repair → Reverify 闭环** ✅ 基础设施存在
   - 修复失败测试
   - 重新验证修复
   - 追溯链路
   - 当前状态：`repair_then_pass` 证据已有

3. **证据分类** ⚠️ 需要标准化
   - `historical_evidence` - 历史数据
   - `fixture_evidence` - Fixture 物化
   - `executed` - 真实执行
   - `reverified=true` - 完成复验

4. **Artifact 管理** ⚠️ 需要完善
   - 路径记录在 `progress.yaml`
   - SHA256 校验
   - Episode 和 FixtureManifest 格式

---

## 2. 现有资产盘点

### ✅ 已有基础设施

#### 脚本
- `scripts/eval/failure/collect_repair_evidence.py` - 收集历史证据
- `scripts/eval/failure/reverify_repair_evidence.py` - 重新验证

#### 实现
- `src/react_agent/eval/repair_executor.py` - Repair 执行器
- `src/react_agent/eval/repair_loop.py` - Repair 循环
- `src/react_agent/harness/evaluation/repair_evidence.py` - 证据处理

#### 证据
- `artifacts/software-delivery/repair_then_pass/` - 完整的 repair 证据
  - `before/` - 修复前状态
  - `repair/` - 修复过程
  - `after/` - 修复后状态
  - `acceptance.json` - 验收结果（reverified: true）
  - `task.json` - 任务元数据

### ⚠️ 缺少的组件

1. **Baseline Compare 模块**
   - 对比逻辑
   - 差异报告生成
   - 统计分析

2. **P4 门禁报告生成器**
   - 聚合所有证据
   - 生成符合 P4 要求的报告
   - SHA256 计算和记录

3. **Progress.yaml 更新逻辑**
   - 自动记录 artifact 路径
   - 计算和存储 SHA256
   - 标记验收状态

---

## 3. 实施方案

### 阶段 1: 创建 Baseline Compare 模块 (2-3 小时)

**文件**: `src/react_agent/harness/evaluation/baseline_compare.py`

**功能**:
```python
def compare_baseline(
    baseline_path: Path,
    current_path: Path
) -> dict:
    """
    对比 baseline 和 current 执行结果
    
    返回:
    {
        "schema_version": "baseline-compare/v1",
        "baseline": {...},
        "current": {...},
        "diff": {
            "test_status_changed": bool,
            "exit_code_changed": bool,
            "performance_delta": {...},
        },
        "summary": {
            "regression_detected": bool,
            "improvement_detected": bool,
        }
    }
    """
```

**测试**: `tests/evaluation/test_baseline_compare.py`

---

### 阶段 2: 创建 P4 报告生成器 (1-2 小时)

**文件**: `scripts/eval/p4/generate_p4_report.py`

**功能**:
```python
def generate_p4_report() -> dict:
    """
    聚合所有 P4 相关证据，生成门禁报告
    
    包括：
    - repair_then_pass 证据
    - baseline compare 结果
    - 所有 artifact 的 SHA256
    - 证据分类标记
    
    输出到: artifacts/harness/p4-acceptance-report.json
    """
```

**输出格式**:
```json
{
  "schema_version": "p4-acceptance/v1",
  "timestamp": "2026-10-19T...",
  "baseline_compare": {
    "report": "artifacts/harness/baseline-compare-latest.json",
    "sha256": "...",
    "status": "passed"
  },
  "repair_reverify_closure": {
    "evidence_path": "artifacts/software-delivery/repair_then_pass",
    "acceptance": "artifacts/software-delivery/repair_then_pass/acceptance.json",
    "sha256": "...",
    "reverified": true,
    "status": "passed"
  },
  "evidence_classification": {
    "historical_evidence": ["..."],
    "fixture_evidence": ["..."],
    "executed": ["..."]
  },
  "summary": {
    "all_requirements_met": true,
    "baseline_compare_exists": true,
    "repair_reverify_traceable": true,
    "artifacts_validated": true
  }
}
```

---

### 阶段 3: 更新 Progress.yaml (30 分钟)

**任务**:
1. 计算所有 P4 artifact 的 SHA256
2. 更新 `progress.yaml` 的 P4 section
3. 使用 `spec_workflow.py update` 标记 P4-1 complete

**更新内容**:
```yaml
P4:
  acceptance:
    - id: P4-1
      status: complete
      evidence:
        - docs/spec/HARNESS_BUILD_SPEC.md
        - artifacts/harness/p4-acceptance-report.json
      artifacts:
        - path: artifacts/harness/baseline-compare-latest.json
          sha256: "..."
        - path: artifacts/software-delivery/repair_then_pass/acceptance.json
          sha256: "..."
      notes: "Baseline compare report generated, repair→reverify closure verified with reverified=true"
```

---

### 阶段 4: 创建测试和文档 (1 小时)

**测试**:
- `tests/evaluation/test_baseline_compare.py` - baseline 对比测试
- `tests/evaluation/test_p4_report_generation.py` - 报告生成测试

**文档**:
- `docs/P4_IMPLEMENTATION_REPORT.md` - 实施报告
- `docs/P4_ACCEPTANCE_EVIDENCE.md` - 验收证据说明

---

## 4. 工作量估算

| 阶段 | 任务 | 估算时间 | 优先级 |
|------|------|----------|--------|
| 1 | Baseline Compare 模块 | 2-3 小时 | 高 |
| 2 | P4 报告生成器 | 1-2 小时 | 高 |
| 3 | Progress.yaml 更新 | 30 分钟 | 高 |
| 4 | 测试和文档 | 1 小时 | 中 |
| **总计** | | **4.5-6.5 小时** | |

---

## 5. 依赖和风险

### 依赖
- ✅ 已有 repair 证据（artifacts/software-delivery/repair_then_pass）
- ✅ 已有基础设施（repair_executor, repair_evidence）
- ✅ Docker 环境（用于 reverify，可选）

### 风险
- ⚠️ **中等风险**: Baseline compare 逻辑复杂性
  - 缓解：先实现简单版本，逐步完善

- ⚠️ **低风险**: 证据格式兼容性
  - 缓解：使用已有的 Episode 和 FixtureManifest 格式

- ⚠️ **低风险**: SHA256 计算错误
  - 缓解：使用标准库，添加验证测试

---

## 6. 验收检查清单

P4-1 完成的标志：

- [ ] `artifacts/harness/baseline-compare-latest.json` 存在
- [ ] `artifacts/harness/p4-acceptance-report.json` 存在
- [ ] `progress.yaml` 中记录了所有 artifact 路径和 SHA256
- [ ] `repair_then_pass/acceptance.json` 中 `reverified=true`
- [ ] 所有证据按 `historical_evidence`, `fixture_evidence`, `executed` 分类
- [ ] P4 门禁测试通过：`python scripts/ci/harness_stage_gate.py --stage P4`
- [ ] 使用 `spec_workflow.py update` 标记 P4-1 为 complete

---

## 7. 实施顺序建议

### 快速路径（核心功能）
1. ✅ 使用现有 repair 证据
2. → 创建简化的 baseline compare
3. → 生成 P4 报告
4. → 更新 progress.yaml
5. → 运行门禁验证

### 完整路径（生产级）
1. → 实现完整的 baseline compare 模块
2. → 添加统计分析和趋势检测
3. → 支持多个 repair 场景
4. → 完整的测试覆盖
5. → 详细的文档

**推荐**: 先走快速路径完成 P4-1，后续迭代完善

---

## 8. 后续改进机会

完成 P4-1 后可以考虑：

1. **自动化 Baseline Refresh**
   - 定期更新 baseline
   - 检测回归

2. **可视化报告**
   - HTML 格式的对比报告
   - 趋势图表

3. **多场景支持**
   - 支持更多 repair 场景
   - 批量对比

4. **CI 集成**
   - PR 自动运行对比
   - 回归警告

---

## 9. 参考资料

### 已有实现
- P3 integration pattern: `src/react_agent/eval/execution_scorer.py`
- Episode format: `src/react_agent/harness/contracts.py`
- Repair evidence: `artifacts/software-delivery/repair_then_pass/`

### Spec 文档
- `docs/spec/HARNESS_BUILD_SPEC.md` - Phase 4 定义
- `docs/spec/goals/harness.md` - P4-1 验收标准
- `docs/spec/HARNESS_PROGRESS.md` - 进度格式

### 相关脚本
- `scripts/eval/failure/collect_repair_evidence.py`
- `scripts/eval/failure/reverify_repair_evidence.py`

---

## 10. 决策点

需要在实施前确认：

### 决策 1: Baseline Compare 范围
- **选项 A**: 简单版（文件级对比，状态比较）- 1 小时
- **选项 B**: 完整版（性能分析，趋势检测）- 3 小时
- **推荐**: 选项 A（先完成 P4-1）

### 决策 2: 证据重用
- **选项 A**: 使用现有 `repair_then_pass` 证据
- **选项 B**: 重新运行 reverify 生成新证据
- **推荐**: 选项 A（已有 reverified=true）

### 决策 3: 报告格式
- **选项 A**: JSON only
- **选项 B**: JSON + Markdown summary
- **推荐**: 选项 A（与 P2/P3 一致）

---

## 总结

**P4-1 完成路径**：
1. 创建简化的 baseline compare (1-2h)
2. 生成 P4 报告聚合证据 (1-2h)
3. 更新 progress.yaml (0.5h)
4. 验证门禁通过 (0.5h)

**总投入**: 3-5 小时

**成功标志**: P4 门禁 PASSED，所有验收标准满足

**下一步**: 确认是否继续执行，或留待后续
