# 文档贡献指南

**目的：** 保持文档结构清晰、可维护，防止目录混乱。

**受众：** 所有贡献者（人类开发者、AI Agent、协作者）

---

## 📂 文档目录结构

```
docs/
├── README.md                    # 📖 文档导航入口
├── CONTRIBUTING_DOCS.md         # 📜 本文档
│
├── guides/                      # 📚 使用指南
│   └── README.md
│
├── architecture/                # 🏗️ 架构设计
│   ├── README.md
│   ├── core-architecture.md
│   ├── structure.md
│   └── agent-workflow.md
│
├── features/                    # ✨ 功能说明
│   ├── README.md
│   ├── plugins.md
│   ├── application-direction.md
│   └── ...
│
├── specs/                       # 📋 规格定义（按模块）
│   ├── README.md
│   ├── harness/
│   │   ├── spec.md              # 主规格
│   │   ├── redis-deployment.md  # 子规格/模块
│   │   ├── migration-guide.md   # 迁移指南
│   │   └── evidence/            # 验收证据
│   │       ├── phase3-completion.md
│   │       ├── phase4-completion.md
│   │       └── baseline-20261014.md
│   │
│   ├── expense/
│   │   ├── workflow-decision-spec.md
│   │   ├── form-workflow-spec.md
│   │   └── evidence/
│   │       └── coverage-matrix-v1.md
│   │
│   └── redis-task/
│       └── mvp-spec.md
│
├── testing/                     # 🧪 测试与评测
│   ├── README.md
│   ├── frameworks/              # 评测框架定义
│   │   ├── harness-health.md
│   │   ├── evidence-map.md
│   │   └── capability-scoring.md
│   │
│   └── baselines/               # 评测基线
│       ├── README.md
│       ├── current/             # 当前基线（回归对比用）
│       │   └── *.json
│       └── archive/             # 历史归档（按季度）
│           └── 2026-q3/
│
├── operations/                  # 🔧 运维与流程
│   ├── README.md
│   ├── failure-regression.md
│   └── ci-improvements.md
│
├── archive/                     # 📦 历史归档（可选）
│   └── 2026-q4/
│
├── STATUS.md                    # 📌 根目录保留文档
├── ROADMAP.md
├── PRODUCTION_MATURITY.md
├── PROJECT_CONTEXT.md
└── EXPERIMENTAL.md
```

---

## 🎯 核心原则

### 原则 1: 单一职责
**每个目录只负责一类文档。**

- `guides/` - 只放使用指南
- `architecture/` - 只放架构设计
- `specs/` - 只放规格定义
- 不要混合不同类型的文档

### 原则 2: 物理分组
**相关的文档物理上放在一起。**

- 每个 spec 独立子目录
- 验收证据与 spec 在一起
- 不要把相关文档分散在不同目录

### 原则 3: 明确生命周期
**区分"活文档"、"稳定文档"、"归档文档"。**

- 活文档（经常更新）→ 根目录或顶层
- 稳定文档（很少改）→ 分类目录
- 归档文档（不再改）→ `archive/`

---

## 📝 新建文档：决策树

### 步骤 1: 确定文档类型

| 我要写... | 应该放在... | 文件名示例 |
|----------|-----------|-----------|
| **使用教程、操作指南** | `guides/` | `getting-started.md`, `deployment-guide.md` |
| **架构设计、技术决策** | `architecture/` | `core-architecture.md`, `data-flow.md` |
| **功能说明、特性文档** | `features/` | `plugins.md`, `rag-system.md` |
| **规格定义** | `specs/{module}/spec.md` | `harness/spec.md`, `expense/workflow-spec.md` |
| **验收报告、测试证据** | `specs/{module}/evidence/` | `evidence/phase4-completion.md` |
| **评测框架定义** | `testing/frameworks/` | `capability-scoring.md` |
| **评测结果/基线** | `testing/baselines/current/` | `capability-baseline-20261019.json` |
| **运维流程、CI 文档** | `operations/` | `failure-regression.md` |
| **临时记录、会话总结** | `archive/{period}/` 或删除 | `session-2026-10-19.md` |

### 步骤 2: 检查是否需要新建子目录

**何时创建新的模块子目录？**

在 `specs/{module}/` 下创建新子目录的条件：
- ✅ 这是一个独立的功能模块（如 harness, expense, redis）
- ✅ 该模块有自己的规格定义
- ✅ 可能有多个相关文档（spec + evidence + guides）

❌ **不要创建的情况：**
- 只有一个小文档
- 这个功能属于现有模块的一部分
- 不确定时，先放在父目录

### 步骤 3: 检查命名规范

**文件命名规则：**

✅ **推荐：**
- 小写字母 + 连字符：`core-architecture.md`
- 清晰描述内容：`plugin-user-guide.md`
- 模块前缀（可选）：`harness-spec.md`

❌ **避免：**
- 大写字母：`CORE_ARCHITECTURE.md`（根目录顶级文档除外）
- 下划线：`core_architecture.md`
- 过长名称：`this-is-a-very-long-file-name-that-nobody-wants-to-type.md`
- 缩写：`arch.md`, `impl.md`（不清楚）
- 带日期（归档除外）：`spec-20261019.md`

---

## ✅ DO：推荐的做法

### 1. 创建新的功能规格

```bash
# ✅ 正确做法
mkdir -p docs/specs/new-module
touch docs/specs/new-module/spec.md
mkdir docs/specs/new-module/evidence
```

在 `spec.md` 中包含：
- 状态（Proposed / Approved / Implemented）
- 范围（做什么 / 不做什么）
- 依赖
- 验收标准

### 2. 添加验收证据

```bash
# ✅ 与规格在一起
docs/specs/harness/evidence/phase4-completion.md
```

### 3. 更新评测基线

```bash
# ✅ 保持 current/ 只有最新的
mv docs/testing/baselines/current/capability-baseline-20260915.json \
   docs/testing/baselines/archive/2026-q3/

cp new-baseline.json \
   docs/testing/baselines/current/capability-baseline-20261019.json
```

### 4. 归档临时文档

```bash
# ✅ 重构完成后，把过程文档归档
mkdir -p docs/archive/2026-q4/refactoring
mv docs/plugin-refactoring-*.md docs/archive/2026-q4/refactoring/
```

---

## ❌ DON'T：禁止的做法

### 1. ❌ 在根目录创建新文档

```bash
# ❌ 错误
docs/my-new-feature.md

# ✅ 正确
docs/features/my-new-feature.md
```

**例外：** 只有以下顶级文档允许在根目录：
- `README.md`, `CONTRIBUTING_DOCS.md`
- `STATUS.md`, `ROADMAP.md`
- `PRODUCTION_MATURITY.md`, `PROJECT_CONTEXT.md`
- `EXPERIMENTAL.md`（重定向页面）

### 2. ❌ 混合规格和报告

```bash
# ❌ 错误：把验收报告和规格混在一起
docs/specs/harness-spec-and-phase4-report.md

# ✅ 正确：分离
docs/specs/harness/spec.md
docs/specs/harness/evidence/phase4-completion.md
```

### 3. ❌ 在主目录保留历史快照

```bash
# ❌ 错误：旧快照堆积
docs/testing/baselines/current/capability-baseline-20260713.json
docs/testing/baselines/current/capability-baseline-20260815.json
docs/testing/baselines/current/capability-baseline-20261019.json

# ✅ 正确：只保留最新的，旧的归档
docs/testing/baselines/current/capability-baseline-20261019.json
docs/testing/baselines/archive/2026-q3/capability-baseline-20260713.json
```

### 4. ❌ 创建语义不清的目录

```bash
# ❌ 错误
docs/misc/
docs/temp/
docs/old/
docs/stuff/

# ✅ 正确：使用明确的分类
docs/archive/2026-q3/
```

### 5. ❌ 在 specs/ 根目录直接放文件

```bash
# ❌ 错误
docs/specs/harness-spec.md
docs/specs/expense-spec.md

# ✅ 正确：每个模块一个子目录
docs/specs/harness/spec.md
docs/specs/expense/workflow-spec.md
```

---

## 🔄 常见场景

### 场景 1: 我完成了一个新功能

**需要的文档：**
1. 功能说明 → `docs/features/{feature}.md`
2. 使用指南 → `docs/guides/using-{feature}.md`
3. 架构变更（如果有）→ 更新 `docs/architecture/core-architecture.md`

### 场景 2: 我要添加一个新模块规格

**步骤：**
```bash
# 1. 创建模块目录
mkdir -p docs/specs/my-module
mkdir -p docs/specs/my-module/evidence

# 2. 创建规格文件
cat > docs/specs/my-module/spec.md << 'EOF'
# My Module Spec

## 状态
Proposed

## 范围
...
EOF

# 3. 创建 README（可选）
echo "# My Module Spec" > docs/specs/my-module/README.md
```

### 场景 3: 我跑了一次评测

**如果这是新的 baseline：**
```bash
# 1. 归档旧的
mkdir -p docs/testing/baselines/archive/2026-q4
mv docs/testing/baselines/current/*.json \
   docs/testing/baselines/archive/2026-q4/

# 2. 保存新的
cp my-eval-results.json \
   docs/testing/baselines/current/capability-baseline-20261019.json
```

**如果只是临时测试：**
```bash
# 不要提交到 docs/，放在 artifacts/ 或本地
./artifacts/test-run-20261019.json
```

### 场景 4: 我完成了一个 Phase 的验收

```bash
# ✅ 验收报告放在对应 spec 的 evidence/
docs/specs/harness/evidence/phase5-completion.md
```

### 场景 5: 我要写会话总结/重构报告

**完成后归档或删除：**
```bash
# 临时文档放在 archive/
docs/archive/2026-q4/sessions/session-2026-10-19.md
docs/archive/2026-q4/refactoring/plugin-refactoring-summary.md
```

**或者直接不提交（只在本地保留）。**

---

## 🧹 定期维护

### 每季度（建议）

1. **归档旧的评测基线**
   ```bash
   mkdir -p docs/testing/baselines/archive/2026-q{N}
   mv docs/testing/baselines/current/*.json \
      docs/testing/baselines/archive/2026-q{N}/
   ```

2. **清理 archive/**
   ```bash
   # 删除超过1年的归档
   rm -rf docs/archive/2025-*/
   ```

3. **检查根目录**
   ```bash
   # 确保只有允许的顶级文档
   ls docs/*.md
   ```

### 每次 PR Review

检查：
- [ ] 新文档是否在正确的目录？
- [ ] 文件命名是否符合规范？
- [ ] 是否有文档在根目录（除了允许的）？
- [ ] 是否有历史快照没有归档？

---

## 🤖 Agent 特别注意

如果你是 AI Agent，在创建或移动文档前：

1. **阅读本指南**
2. **检查目标目录的 README.md**，确认该目录的职责
3. **不确定时，询问用户**，而不是猜测
4. **遵守 DO/DON'T 规则**
5. **记录你的决策理由**（在 commit message 中）

---

## 📞 寻求帮助

**不确定文档应该放在哪里？**

1. 查看本指南的"决策树"部分
2. 查看目标目录的 README.md
3. 查看类似的现有文档放在哪里
4. 如果还不确定，在 PR/Issue 中提问

---

## 📚 相关文档

- [文档导航](README.md) - 文档目录总览
- [项目结构](architecture/structure.md) - 整体代码和文档结构
- [贡献指南](../CONTRIBUTING.md) - 代码贡献指南

---

**版本：** v1.0  
**最后更新：** 2026-10-20  
**维护者：** 项目维护团队
