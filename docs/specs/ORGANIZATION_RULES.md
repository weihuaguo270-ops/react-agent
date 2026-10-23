# 规格文档组织规则

## 📋 目的

明确定义：
1. 什么情况下需要创建独立文档？
2. 规格（R 系列）和验收（P 系列）如何组织？
3. 如何保持文档结构一致？

---

## 🎯 核心原则

### 原则 1: 主规格是唯一真相来源

**每个模块只有一个主规格文档**，记录：
- 目标和范围
- 所有 Requirements（R1-RN）
- 所有 Phases（P0-PN）
- 完成状态

**示例：**
- `specs/harness/spec.md` - Harness 的唯一主规格

### 原则 2: 子规格按复杂度决定

**何时创建独立的子规格文档？**

✅ **需要独立文档的情况：**
- 超过 200 行的详细技术说明
- 需要独立演进和维护
- 涉及跨团队/跨模块集成
- 需要独立的技术评审

❌ **不需要独立文档的情况：**
- 少于 200 行的简单说明
- 只是主规格的一个章节
- 不需要独立评审

**示例：**
```
# ✅ 需要独立文档
specs/harness/r6-observability.md
# 理由：Redis 部署、告警接线、复杂配置，超过 200 行

# ❌ 不需要独立文档  
R1: 工具协议统一
# 理由：简单的接口定义，在主规格中作为一节即可
```

### 原则 3: 验收报告按 Phase 组织

**每个 Phase 完成后，必须有验收报告**

**验收报告存放位置：**
```
specs/{module}/evidence/
├── phase0-baseline.md        # Phase 0 基线冻结
├── phase1-completion.md       # Phase 1 完成报告
├── phase2-completion.md       # Phase 2 完成报告
├── phase3-completion.md       # Phase 3 完成报告
├── phase4-completion.md       # Phase 4 完成报告
└── phase5-migration.md        # Phase 5 迁移完成
```

**验收报告必须包含：**
- Phase 目标
- 验收标准
- 完成状态（Complete / Partial / In Progress）
- 证据链接（artifacts, test results, git commits）
- 遗留问题（如果有）

---

## 📂 标准目录结构

### 简单模块（Requirements < 3 个）

```
specs/{module}/
├── spec.md           # 唯一规格文档（包含所有 R 和 P）
└── evidence/         # 验收证据
    ├── phase1-completion.md
    ├── phase2-completion.md
    └── ...
```

### 复杂模块（Requirements ≥ 3 个，且有复杂子规格）

```
specs/{module}/
├── spec.md           # 主规格（总览 + 简单的 R）
├── r{N}-{name}.md    # 复杂的子规格（独立文档）
└── evidence/         # 验收证据
    ├── phase0-baseline.md
    ├── phase1-completion.md
    └── ...
```

**示例：Harness（复杂模块）**
```
specs/harness/
├── spec.md                   # 主规格
│   ├── 总览
│   ├── R1: 工具协议统一（简单，在主规格中）
│   ├── R2: 重试策略（简单，在主规格中）
│   ├── R3-R5: ...（简单，在主规格中）
│   └── R6: 可观测性（复杂，见独立文档）
│
├── r6-observability.md       # R6 独立子规格（复杂）
├── migration-guide.md        # 迁移指南（可选）
│
└── evidence/                 # 验收证据
    ├── phase0-baseline.md
    ├── phase1-completion.md
    ├── phase2-completion.md
    ├── phase3-completion.md
    ├── phase4-completion.md
    └── phase5-migration/     # P5 很复杂，有多个子文档
        ├── summary.md
        ├── batch1-report.md
        ├── inventory.md
        └── plan.md
```

---

## 📝 文件命名规则

### 主规格
```
spec.md
```

### 子规格（R 系列）
```
r{N}-{feature}.md

示例：
r6-observability.md
r3-orchestration.md
```

### 验收报告（P 系列）
```
phase{N}-{milestone}.md

示例：
phase0-baseline.md
phase1-completion.md
phase4-completion.md
phase5-migration.md
```

### 复杂 Phase 的子文档
```
phase{N}-{milestone}/
├── summary.md
├── batch{N}-report.md
└── ...

示例：
phase5-migration/
├── summary.md
├── batch1-report.md
├── inventory.md
└── plan.md
```

---

## ✅ 决策流程图

### 我要记录一个 Requirement

```
是否超过 200 行？
├─ 否 → 在主规格中作为一节
└─ 是 → 创建 r{N}-{feature}.md
```

### 我完成了一个 Phase

```
必须创建验收报告
└─ specs/{module}/evidence/phase{N}-completion.md

验收报告是否很复杂（多个方面、批次）？
├─ 否 → 单个文件
└─ 是 → 创建子目录
    └─ phase{N}-{milestone}/
        ├── summary.md
        └── ...
```

### 我要添加迁移指南、部署文档

```
是否属于某个 Requirement？
├─ 是 → 在对应的 r{N}.md 中
└─ 否 → 创建独立文档
    ├── migration-guide.md
    ├── deployment.md
    └── ...
```

---

## 🔍 检查清单

### 创建新模块规格时

- [ ] 是否创建了主规格 `spec.md`？
- [ ] 是否明确了所有 Requirements（R1-RN）？
- [ ] 是否明确了所有 Phases（P0-PN）？
- [ ] 是否创建了 `evidence/` 目录？
- [ ] 复杂的 Requirement 是否拆分为独立文档？

### 完成一个 Phase 时

- [ ] 是否创建了验收报告？
- [ ] 验收报告是否包含完成状态？
- [ ] 验收报告是否包含证据链接？
- [ ] 是否更新了主规格中的 Phase 状态？

### 文档审查时

- [ ] 是否所有 Phase 都有对应的验收报告？
- [ ] 是否有独立的子规格但没有在主规格中引用？
- [ ] 是否有超过 200 行的内容应该拆分？
- [ ] 文件命名是否符合规范？

---

## 📊 Harness 案例：应该有哪些文档？

### 当前 HARNESS_BUILD_SPEC.md 定义：

**R 系列：** R1, R2, R3, R4, R5, R6  
**P 系列：** Phase 0, 1, 2, 3, 4, 5

### 按规则应该有的文档结构：

```
specs/harness/
├── spec.md                          # 主规格（包含 R1-R5 的简要说明）
├── r6-observability.md              # R6 独立（超过 200 行）
│
└── evidence/                        # 验收证据
    ├── phase0-baseline.md           # ✅ 应该有（在 evaluation/）
    ├── phase1-completion.md         # ❌ 缺失（需要补充或标记不需要）
    ├── phase2-completion.md         # ❌ 缺失
    ├── phase3-completion.md         # ❌ 缺失
    ├── phase4-completion.md         # ✅ 存在
    └── phase5-migration/            # ✅ 存在（多个子文档）
        ├── summary.md
        ├── batch1-report.md
        ├── inventory.md
        ├── plan.md
        └── status.md
```

### 缺失的文档处理：

**Phase 1-3 的验收报告缺失，有三种处理方式：**

1. **补充验收报告** - 如果有证据，补充文档
2. **标记为隐式验收** - 在主规格中说明"Phase 1-3 的验收证据在 git commits / issues 中"
3. **合并到一个报告** - 创建 `phase1-3-retrospective.md` 说明早期 Phase 的完成情况

**我的建议：** 选择方案 2，在主规格中添加一节：

```markdown
## 验收证据

### Phase 0-3: 隐式验收
Phase 0-3 在早期完成，验收证据散落在：
- Git commits: [commit range]
- Issues: [#123, #456]
- 完成时没有独立的验收报告文档

### Phase 4: 显式验收
参见 [`evidence/phase4-completion.md`](evidence/phase4-completion.md)

### Phase 5: 显式验收
参见 [`evidence/phase5-migration/`](evidence/phase5-migration/)
```

---

## 🚫 禁止的做法

### 1. ❌ 在根目录放零散的 Phase 报告
```bash
# ❌ 错误
docs/specs/harness/evidence/phase4-completion.md
docs/specs/harness/evidence/phase5-migration/summary.md

# ✅ 正确
docs/specs/harness/evidence/phase4-completion.md
docs/specs/harness/evidence/phase5-migration/summary.md
```

### 2. ❌ 创建没有主规格的子规格
```bash
# ❌ 错误：只有 R6，没有主规格
docs/specs/harness/r6-observability.md

# ✅ 正确：先有主规格
docs/specs/harness/spec.md        # 引用 R6
docs/specs/harness/r6-observability.md
```

### 3. ❌ Phase 完成但没有任何记录
```bash
# ❌ 错误：Phase 2 标记 Complete，但没有验收报告

# ✅ 正确：至少在主规格中说明验收方式
## Phase 2 验收
在 git commits abc123..def456 中完成，验收通过 PR #789
```

---

## 📚 相关文档

- [文档贡献指南](../CONTRIBUTING_DOCS.md) - 通用文档规则
- [规格目录说明](README.md) - 规格目录职责

---

**版本：** v1.0  
**创建：** 2026-10-20  
**维护：** 项目维护团队
