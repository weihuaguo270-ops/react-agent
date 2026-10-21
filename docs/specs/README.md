# 规格目录

存放功能模块的规格定义和验收证据。

---

## 📋 职责

- **存放内容：** 功能模块的规格定义（Spec）和验收证据（Evidence）
- **不存放：** 实施进度、临时文档、评测结果

---

## 📂 结构

每个模块一个子目录：

```
specs/
├── {module}/
│   ├── spec.md              主规格文档
│   ├── {submodule}.md       子模块规格（可选）
│   ├── migration-guide.md   迁移指南（可选）
│   └── evidence/            验收证据
│       ├── phase{N}-completion.md
│       └── baseline-YYYYMMDD.md
```

---

## 📝 规格文件应该包含什么？

### 必须包含：
- **状态** - Proposed / Approved / Implemented / Deprecated
- **范围** - 做什么 / 不做什么（清晰的边界）
- **依赖** - 需要哪些前置条件
- **验收标准** - 如何判断完成

### 可选包含：
- 技术选型
- 实施计划（概要）
- 风险和限制
- 相关链接

### 不应该包含：
- ❌ 详细的实施进度（属于项目管理）
- ❌ 验收报告（放在 evidence/）
- ❌ 评测结果（放在 testing/）

---

## ✅ DO：推荐做法

### 1. 每个模块独立子目录
```bash
mkdir -p docs/specs/my-module
mkdir -p docs/specs/my-module/evidence
```

### 2. 规格和证据分离
```
specs/harness/
├── spec.md           # 规格定义（稳定后冻结）
└── evidence/         # 验收证据（阶段性添加）
    ├── phase0-baseline.md
    ├── phase3-completion.md
    ├── phase4-completion.md
    ├── phase4-plan.md
    └── phase5-migration/
        ├── summary.md
        ├── batch1-report.md
        └── ...
```

### 3. 规格完成后冻结
- 规格定义应该在实施前确定
- 实施过程中如果需要变更，应该记录变更原因
- 已完成的规格不要频繁修改

---

## ❌ DON'T：禁止做法

### 1. ❌ 不要在根目录直接放规格
```bash
# ❌ 错误
docs/specs/harness-spec.md

# ✅ 正确
docs/specs/harness/spec.md
```

### 2. ❌ 不要混合不同模块
```bash
# ❌ 错误
docs/specs/harness-and-expense-spec.md

# ✅ 正确
docs/specs/harness/spec.md
docs/specs/expense/spec.md
```

### 3. ❌ 不要混合规格和报告
```bash
# ❌ 错误：把验收报告混在规格中
docs/specs/harness/spec-with-phase4-report.md

# ✅ 正确：分离
docs/specs/harness/spec.md
docs/specs/harness/evidence/phase4-completion.md
```

### 4. ❌ 不要在规格中写进度
```markdown
# ❌ 错误：规格中写实施进度
## 实施进度
- [x] Week 1: 完成设计
- [ ] Week 2: 开发中...

# ✅ 正确：进度属于项目管理，不在规格中
```

---

## 📁 现有模块

### Harness - Harness 构建与统一契约
- **规格**: [`harness/spec.md`](harness/spec.md)
- **状态**: Proposed (实施中)
- **代码结构**: 
  - ✅ `src/react_agent/harness/contracts/` - Phase 1 Shared Contracts
  - ✅ `src/react_agent/harness/runtime/` - Phase 2 Runtime 收敛
  - ✅ `src/react_agent/harness/evaluation/` - Phase 3 Evaluation 收敛
- **进度**: 
  - ✅ Phase 0: Complete (基线冻结)
  - ✅ Phase 1: Complete (contracts/ 已实现)
  - ✅ Phase 2: Complete (runtime/ 已实现)
  - ✅ Phase 3: Complete (evaluation/ 已实现)
  - ⚠️ Phase 4: Partial (Baseline/repair/reverify，Windows 环境问题待解决)
  - 🔄 Phase 5: In Progress (兼容期迁移，22个导入站点待迁移)
- **验收证据**: [`harness/evidence/`](harness/evidence/)

### Expense - Expense 工作流与决策
- **规格**: 
  - [`expense/workflow-decision-spec.md`](expense/workflow-decision-spec.md)
  - [`expense/form-workflow-spec.md`](expense/form-workflow-spec.md)
  - [`expense/policy-boundary-spec.md`](expense/policy-boundary-spec.md)
- **代码**: `src/react_agent/apps/expense/` (8个Python文件)
- **测试**: `tests/apps/expense/` (8个测试文件)
- **状态**: Hold (等待业务确认)
- **进度**: S1 baseline 已冻结 (2026-10-12)，代码完整但暂停开发
- **验收证据**: [`expense/evidence/`](expense/evidence/)

### Redis Task - Redis 任务队列 MVP
- **规格**: [`redis-task/mvp-spec.md`](redis-task/mvp-spec.md)
- **代码**: ❌ 未实现
- **状态**: 规格定义阶段
- **进度**: 规格已编写，尚未开始实施

### docs_troubleshoot - 证据化文档排障
- **代码**: `src/react_agent/apps/docs_troubleshoot/` (21个Python文件)
- **评测**: `scripts/eval/docs/` (4个评测脚本)
- **状态**: ✅ Active (在 CI 中运行)
- **说明**: 这是"客服/自动化"方向下的垂直 demo

---

## 🆕 添加新模块规格

### 步骤：

1. **创建模块目录**
   ```bash
   mkdir -p docs/specs/my-module
   mkdir -p docs/specs/my-module/evidence
   ```

2. **创建规格文件**
   ```bash
   cat > docs/specs/my-module/spec.md << 'EOF'
   # My Module Spec
   
   ## 状态
   Proposed
   
   ## 范围
   ### 包含
   - ...
   
   ### 不包含
   - ...
   
   ## 验收标准
   - [ ] ...
   EOF
   ```

3. **创建 README（可选）**
   ```bash
   echo "# My Module" > docs/specs/my-module/README.md
   ```

---

## 📚 相关文档

- [文档贡献指南](../CONTRIBUTING_DOCS.md) - 了解文档规则
- [文档导航](../README.md) - 返回文档首页

---

**维护：** 项目维护团队  
**更新：** 2026-10-20
