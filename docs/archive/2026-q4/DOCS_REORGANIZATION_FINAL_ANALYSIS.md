# docs/ 目录重组 - 核心问题分析

## 🤔 首先要回答的根本问题

**docs/ 目录是为谁设计的？**

### 选项 1: 给人读的文档
- **目的**: 开发者理解项目、使用功能、贡献代码
- **组织原则**: 按用户任务和认知流程组织（"我想做什么"）
- **典型结构**: Getting Started → Guides → API Reference → Architecture

### 选项 2: 给 Agent/RAG 读的语料
- **目的**: Agent 检索知识、回答问题
- **组织原则**: 按主题域和检索效率组织（"回答什么类型的问题"）
- **典型结构**: 扁平化主题文档，避免过深嵌套

### 选项 3: 项目档案/证据库
- **目的**: 记录项目历史、验收证据、规格演进
- **组织原则**: 按时间线和规格版本组织
- **典型结构**: specs/ + reports/ + baselines/

## 🔍 当前 docs/ 的实际用途分析

让我逐个文件分析它们的实际用途：

### 当前文档分类

| 文档 | 实际用途 | 读者 | 更新频率 |
|------|---------|------|---------|
| STATUS.md | 项目当前状态 | 人 | 经常 |
| ROADMAP.md | 未来计划 | 人 | 偶尔 |
| CORE_ARCHITECTURE.md | 架构设计 | 人/Agent | 稳定 |
| PLUGINS.md | 功能文档 | 人 | 稳定 |
| HARNESS_BUILD_SPEC.md | **规格定义** | 人（实施者） | 稳定后冻结 |
| P4_COMPLETION_REPORT.md | **验收证据** | 人（审查者） | 写一次 |
| HARNESS_PROGRESS.md | **进度追踪** | 人（PM） | 频繁更新 |
| capability_snapshot_*.json | **评测数据** | 程序/人（分析） | 归档 |
| EXPENSE_COVERAGE_MATRIX.md | **测试矩阵** | 人（测试者） | 随spec更新 |

## 📋 关键发现

### 1. evaluation/ 目录问题

**当前内容：**
- `HARNESS_HEALTH.md` - 这不是评测结果，是**评测标准定义**
- `P0_EVIDENCE_MAP.md` - 证据地图，不是评测结果
- `HARNESS_BASELINE_20261014.md` - 基线定义
- `expense/` - Expense 评测覆盖矩阵

**问题：混淆了"评测标准/框架"和"评测结果"**

### 2. spec/ 目录问题

**以 Harness 为例：**
```
HARNESS_BUILD_SPEC.md         # 规格定义（What to build）
HARNESS_PROGRESS.md            # 进度追踪（实施过程）
HARNESS_R6_REDIS_DEPLOYMENT.md # 部署规格（子模块）
P3-3_COMPLETION_REPORT.md      # 验收报告（Phase 3完成证明）
P4_COMPLETION_REPORT.md        # 验收报告（Phase 4完成证明）
P4_IMPLEMENTATION_PLAN.md      # 实施计划（Phase 4的细节）
P5_*.md                         # Phase 5 系列文档
```

**问题：混淆了"规格"、"计划"、"进度"、"报告"四个概念**

### 3. snapshots/ 的真实内容

```bash
Jul 13: capability_*.json, eval_report_*.json
Jul 15: execution_*.json, reliability_*.json  
Jul 16: flywheel_*.json, reliability_*.json
Aug 13: github_portfolio_dataset_*.json
```

**这些是：某次评测运行的结果快照，用于回归对比**

- **最新的是 8月13日**（github_portfolio）
- **最旧的是 7月13日**（capability）
- **用途：回归测试时对比新旧结果**
- **价值：如果有更新的评测结果，旧的就没用了**

## 💡 重新设计原则

### 原则 1: 明确文档的生命周期

| 生命周期 | 典型文档 | 组织方式 |
|---------|---------|---------|
| **活文档** (经常更新) | STATUS, ROADMAP, 开发指南 | 根目录或顶层分类 |
| **稳定文档** (很少改) | 架构设计, 功能说明 | 按主题分类 |
| **归档文档** (写后不改) | 验收报告, 快照数据 | 按时间归档 |

### 原则 2: 区分"定义"和"证据"

| 类型 | 例子 | 位置 |
|------|------|------|
| **定义** | Spec, 标准, 框架 | 主文档区 |
| **证据** | 报告, 快照, 矩阵 | 独立的 evidence/ 或嵌入 spec |

### 原则 3: 人类认知优先

即使有 Agent，文档组织仍应以人类理解为主：
- **浅层目录** - 不超过3层
- **清晰命名** - 目录名直接说明用途
- **关联清晰** - 相关文档物理上接近

## ✅ 我的新方案

```
docs/
├── README.md                    # 导航 + 文档地图
│
├── guides/                      # 📖 使用指南（给用户）
│   ├── getting-started.md
│   ├── plugin-usage.md
│   └── deployment.md
│
├── architecture/                # 🏗️ 架构设计（稳定文档）
│   ├── CORE_ARCHITECTURE.md
│   ├── STRUCTURE.md
│   └── AGENT_WORKFLOW.md
│
├── features/                    # ✨ 功能说明（稳定文档）
│   ├── PLUGINS.md
│   ├── APPLICATION_DIRECTION.md
│   ├── EVIDENCE_DOCS_TROUBLESHOOT.md
│   └── ...
│
├── specs/                       # 📋 规格定义（每个spec一个子目录）
│   ├── harness/
│   │   ├── spec.md              # 主规格
│   │   ├── deployment-redis.md  # 子规格
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
│   ├── frameworks/              # 评测框架定义
│   │   ├── harness-health.md
│   │   ├── evidence-map.md
│   │   └── capability-scoring.md
│   │
│   └── results/                 # 评测结果（可定期清理）
│       └── archive-2026-q3/     # 按季度归档
│           ├── capability-snapshot-20260713.json
│           ├── execution-snapshot-20260715.json
│           └── github-dataset-20260813.json
│
├── operations/                  # 🔧 运维与流程
│   ├── failure-regression.md
│   ├── ci-improvements.md
│   └── artifact-retention.md
│
├── archive/                     # 📦 历史归档（可选）
│   └── 2026-q3/
│       ├── refactoring-reports/
│       └── deprecated-specs/
│
├── STATUS.md                    # 📌 根目录保留
├── ROADMAP.md
├── PRODUCTION_MATURITY.md
└── PROJECT_CONTEXT.md
```

## 🎯 关键改进

### 1. evaluation/ → testing/
- `testing/frameworks/` - 评测框架定义
- `testing/results/` - 评测结果快照（可定期清理）

### 2. spec/ → specs/ + evidence/
- 每个 spec 一个子目录
- `evidence/` 子目录存放验收证据
- 避免混淆 spec、progress、report

### 3. snapshots/ → testing/results/archive-YYYY-QQ/
- 按季度归档
- 明确是"过时的评测结果"
- 可以定期清理（保留最近2个季度）

### 4. 新增 guides/
- 面向用户的使用指南
- 与架构设计文档分离

## 📝 操作建议

### 立即行动
1. 创建新的目录结构
2. 移动活跃文档（STATUS, architecture, features）
3. 重组 specs/（每个spec独立子目录 + evidence/）

### 评估后决定
1. **snapshots/** - 检查最新评测结果日期，旧快照是否还需要？
2. **evaluation/** - 重命名为 testing/，区分框架和结果
3. **refactoring 文档** - 归档到 archive/ 或直接删除

### 定期维护
1. 每季度清理 `testing/results/` 旧快照
2. 完成的 spec evidence 可以合并到 spec 文档
3. archive/ 中超过1年的内容考虑删除

## ❓ 需要你决定

1. **docs/ 的主要读者是谁？**
   - 主要给人读 → 按任务组织
   - 主要给 Agent 读 → 扁平化主题
   - 两者兼顾 → 混合方式

2. **历史快照保留多久？**
   - 保留最近 N 个月？
   - 按季度归档并定期清理？
   - 全部删除（Git 历史中有）？

3. **验收证据如何组织？**
   - 与 spec 放一起（更紧密）
   - 单独的 evidence/ 目录（更清晰）
   - 完成后合并到 spec 文档（更简洁）

请告诉我你的答案，我会据此给出最终方案。
