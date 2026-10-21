# docs/ 目录重组方案 v2（精简版）

## 🔍 重新审视问题

### 你指出的关键问题

1. **Phase 报告不是独立的** - P3/P4/P5 报告是 harness spec 的验收文件，应该与 spec 放在一起
2. **历史快照价值存疑** - 带日期的 snapshot 文件可能已过时，需要评估是否保留
3. **过时文件不应保留** - 不必要的历史文件会增加维护负担

### 需要回答的问题

1. ✅ Phase 报告应该放在哪里？→ 与对应的 spec 文件一起
2. ✅ 历史快照是否有用？→ 需要评估，可能直接删除
3. ✅ 哪些文件是过时的？→ 需要逐一审查

## 📋 文件价值评估

### 核心文档（必须保留）

**架构设计：**
- CORE_ARCHITECTURE.md - 核心架构
- STRUCTURE.md - 仓库结构
- HARNESS_HEALTH.md - Harness健康度
- AGENT_WORKFLOW.md - Agent工作流

**功能说明：**
- APPLICATION_DIRECTION.md - 应用方向
- PLUGINS.md - 插件系统
- EVIDENCE_DOCS_TROUBLESHOOT.md - 文档排障
- GITHUB_DELIVERY_WORKFLOW.md - GitHub交付流程
- DEPLOY.md - 部署文档
- SANDBOX_SECURITY.md - 沙箱安全
- PORTABILITY.md - 可移植性

**评测体系：**
- EVAL_INDEX.md - 评测索引
- DOCS_TROUBLESHOOT_EVAL.md - 文档排障评测
- P0_EVIDENCE_MAP.md - P0证据地图
- SOFTWARE_TASK_DATASET.md - 软件任务数据集

**运维流程：**
- FAILURE_REGRESSION_PIPELINE.md - 失败回归管道
- CI_IMPROVEMENTS.md - CI改进

**项目状态：**
- STATUS.md - 当前状态
- ROADMAP.md - 路线图
- PRODUCTION_MATURITY.md - 成熟度

### 最近的重组文档（保留）

- PLUGIN_REFACTORING_SUMMARY.md - 插件重构总结
- PROJECT_REORGANIZATION_COMPLETE.md - 项目重组完成
- TEMP_DIR_MANAGEMENT.md - 临时目录管理
- SESSION_SUMMARY_2026-10-19.md - 最近的会话记录

### 可能过时的文件（需要评估/删除）

**历史快照（20260713-20260716）：** 14个文件
- capability_newcases_20260713.md
- capability_snapshot_20260713.md
- eval_report_20260713.md
- execution_agent_snapshot_20260715.md
- execution_agent_snapshot_20260715_v2.md
- execution_agent_snapshot_20260716_v3.md
- execution_snapshot_20260715.md
- flywheel_closed_loop_20260716.md
- reliability_live_live_20260716.md
- reliability_live_live_20260716_v2.md
- reliability_live_mock_20260716.md
- reliability_live_mock_20260716_v2.md
- reliability_snapshot_20260715.md
- step_watcher_evidence_baseline.md

**问题：**
- 这些快照是 7月的，现在已经 10月了
- 如果当前状态更好，这些历史快照没有保留价值
- 建议：**直接删除**，除非有特殊的历史追溯需求

**其他可能过时的：**
- EXPERIMENTAL.md - 已被 PLUGINS.md 替代（保留作为重定向）
- REFACTORING_EXPERIMENTAL_TO_PLUGINS.md - 重构计划（可以归档或删除）
- PLUGIN_REFACTORING_COMPLETE.md - 与 SUMMARY 重复

## ✅ 精简重组方案

### 推荐结构

```
docs/
├── README.md                          # 📖 总索引（新建）
│
├── architecture/                      # 🏗️ 核心架构
│   ├── CORE_ARCHITECTURE.md
│   ├── STRUCTURE.md
│   ├── HARNESS_HEALTH.md
│   └── AGENT_WORKFLOW.md
│
├── features/                          # ✨ 功能文档
│   ├── PLUGINS.md
│   ├── APPLICATION_DIRECTION.md
│   ├── EVIDENCE_DOCS_TROUBLESHOOT.md
│   ├── GITHUB_DELIVERY_WORKFLOW.md
│   ├── DEPLOY.md
│   ├── SANDBOX_SECURITY.md
│   └── PORTABILITY.md
│
├── evaluation/                        # 📊 评测（已存在，移入相关文档）
│   ├── EVAL_INDEX.md
│   ├── DOCS_TROUBLESHOOT_EVAL.md
│   ├── P0_EVIDENCE_MAP.md
│   ├── SOFTWARE_TASK_DATASET.md
│   └── expense/
│
├── operations/                        # 🔧 运维
│   ├── FAILURE_REGRESSION_PIPELINE.md
│   ├── CI_IMPROVEMENTS.md
│   └── ARTIFACT_RETENTION.md
│
├── spec/                              # 📋 规范文档（已存在）
│   ├── HARNESS_BUILD_SPEC.md
│   ├── P3-3_COMPLETION_REPORT.md     # ← Harness spec 验收
│   ├── P4_COMPLETION_REPORT.md       # ← Harness spec 验收
│   ├── P5_*.md                        # ← Harness spec 验收
│   └── [其他 spec 文件]
│
├── refactoring/                       # 🔄 重构记录（新建）
│   ├── PLUGIN_REFACTORING_SUMMARY.md
│   ├── PROJECT_REORGANIZATION_COMPLETE.md
│   ├── TEMP_DIR_MANAGEMENT.md
│   └── SESSION_SUMMARY_2026-10-19.md
│
├── guide/                             # 📚 指南（已存在）
├── snapshots/                         # 📸 JSON快照（已存在）
├── daily_smoke/                       # 🔥 每日测试（已存在）
│
├── STATUS.md                          # 📌 保持根目录
├── ROADMAP.md                         # 🗺️ 保持根目录
├── PRODUCTION_MATURITY.md             # 🎯 保持根目录
└── EXPERIMENTAL.md                    # ⚠️ 重定向页面（保留兼容）
```

### 关键改进

1. **Phase 报告放入 spec/** - 与 Harness spec 在一起，逻辑正确
2. **删除历史快照** - 7月的 markdown 快照已过时，直接删除
3. **精简 refactoring/** - 只保留最近的重组记录
4. **reports/ 目录取消** - 不需要单独的 reports 目录

## 🗑️ 建议删除的文件（14个历史快照）

```bash
# 这些是 7月的快照，已经过时 3 个月
rm docs/capability_newcases_20260713.md
rm docs/capability_snapshot_20260713.md
rm docs/eval_report_20260713.md
rm docs/execution_agent_snapshot_20260715.md
rm docs/execution_agent_snapshot_20260715_v2.md
rm docs/execution_agent_snapshot_20260716_v3.md
rm docs/execution_snapshot_20260715.md
rm docs/flywheel_closed_loop_20260716.md
rm docs/reliability_live_live_20260716.md
rm docs/reliability_live_live_20260716_v2.md
rm docs/reliability_live_mock_20260716.md
rm docs/reliability_live_mock_20260716_v2.md
rm docs/reliability_snapshot_20260715.md
rm docs/step_watcher_evidence_baseline.md
```

**理由：**
- 已过时 3 个月
- 如果需要历史记录，Git 历史中有完整保留
- 减少维护负担

## 📝 实施步骤

### Step 1: 创建新目录
```bash
mkdir -p docs/architecture
mkdir -p docs/features
mkdir -p docs/operations
mkdir -p docs/refactoring
```

### Step 2: 移动核心文档
```bash
# 架构
git mv docs/CORE_ARCHITECTURE.md docs/architecture/
git mv docs/STRUCTURE.md docs/architecture/
git mv docs/HARNESS_HEALTH.md docs/architecture/
git mv docs/AGENT_WORKFLOW.md docs/architecture/

# 功能
git mv docs/PLUGINS.md docs/features/
git mv docs/APPLICATION_DIRECTION.md docs/features/
git mv docs/EVIDENCE_DOCS_TROUBLESHOOT.md docs/features/
git mv docs/GITHUB_DELIVERY_WORKFLOW.md docs/features/
git mv docs/DEPLOY.md docs/features/
git mv docs/SANDBOX_SECURITY.md docs/features/
git mv docs/PORTABILITY.md docs/features/

# 评测
git mv docs/EVAL_INDEX.md docs/evaluation/
git mv docs/DOCS_TROUBLESHOOT_EVAL.md docs/evaluation/
git mv docs/P0_EVIDENCE_MAP.md docs/evaluation/
git mv docs/SOFTWARE_TASK_DATASET.md docs/evaluation/

# 运维
git mv docs/FAILURE_REGRESSION_PIPELINE.md docs/operations/
git mv docs/CI_IMPROVEMENTS.md docs/operations/
git mv docs/ARTIFACT_RETENTION.md docs/operations/

# Harness spec 验收报告
git mv docs/P3-3_COMPLETION_REPORT.md docs/spec/
git mv docs/P4_COMPLETION_REPORT.md docs/spec/
git mv docs/P4_IMPLEMENTATION_PLAN.md docs/spec/

# 重构记录
git mv docs/PLUGIN_REFACTORING_SUMMARY.md docs/refactoring/
git mv docs/PROJECT_REORGANIZATION_COMPLETE.md docs/refactoring/
git mv docs/TEMP_DIR_MANAGEMENT.md docs/refactoring/
git mv docs/SESSION_SUMMARY_2026-10-19.md docs/refactoring/
```

### Step 3: 删除过时文件
```bash
# 删除 7月的历史快照（14个）
git rm docs/*_20260713.md
git rm docs/*_20260715.md
git rm docs/*_20260716.md

# 可选：删除重复的重构文档
git rm docs/PLUGIN_REFACTORING_COMPLETE.md  # 与 SUMMARY 重复
git rm docs/REFACTORING_EXPERIMENTAL_TO_PLUGINS.md  # 已完成的计划
```

### Step 4: 创建索引
- 创建 `docs/README.md` 作为文档导航
- 更新各子目录的 README（如需要）

### Step 5: 更新引用
- 更新文档间的相对路径
- 更新根目录 README.md 中的链接

## 📊 重组前后对比

| 项目 | 重组前 | 重组后 | 改善 |
|------|--------|--------|------|
| 根目录文件 | 55个 | 4个 | -51个 ✅ |
| 历史快照 | 14个 | 0个 | 删除 ✅ |
| 文档分类 | 混乱 | 清晰 | 5个类别 ✅ |
| Phase 报告位置 | 根目录 | spec/ | 逻辑正确 ✅ |
| 总文档数 | 55个 | ~35个 | -20个 ✅ |

## ✅ 最终结果

- **根目录干净** - 只保留 4 个最重要的文档
- **逻辑合理** - Phase 报告与 spec 在一起
- **精简有效** - 删除过时快照，减少 20 个文件
- **易于维护** - 按功能分类，清晰明确

需要我执行这个精简方案吗？
