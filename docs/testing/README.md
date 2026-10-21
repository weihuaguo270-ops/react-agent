# 测试与评测

存放评测框架定义和评测基线。

---

## 📋 职责

- **frameworks/** - 评测框架定义（如何评测、评测标准）
- **baselines/** - 评测基线（用于回归对比的快照）

---

## 📂 结构

```
testing/
├── frameworks/           评测框架定义
│   ├── harness-health.md
│   ├── evidence-map.md
│   └── capability-scoring.md
│
└── baselines/            评测基线
    ├── current/          当前基线（回归对比用）
    │   └── *.json
    └── archive/          历史归档（按季度）
        └── 2026-q3/
```

---

## 🎯 frameworks/ - 评测框架定义

### 存放内容：
- 评测标准定义
- 评测方法说明
- 评分规则
- 验收标准

### 实际内容：
- `harness-health.md` - Harness 健康度评测标准
- `evidence-map.md` - 证据地图和验收框架
- `p0-evidence-map.md` - P0 证据地图
- `eval-index.md` - 评测索引
- `docs-troubleshoot-eval.md` - 文档排障评测
- `software-task-dataset.md` - 软件任务数据集
- `software-task-runner.md` - 软件任务运行器
- `evidence.md` - 证据框架
- `step-watcher-baseline.md` - Step Watcher 基线

### 不存放：
- ❌ 评测结果（放在 baselines/）
- ❌ 临时数据（不要提交）

---

## 📸 baselines/ - 评测基线

### 用途：
**回归测试对比** - 当你修改代码后，对比新旧评测结果，检测是否引入退化。

```python
# 示例：baseline compare
compare_baseline(
    baseline_path="docs/testing/baselines/current/capability-baseline.json",
    current_path="artifacts/capability-latest.json"
)
# 输出：regression_detected: True/False
```

### 目录说明：

#### `current/` - 当前基线
- **存放：** 最新的评测结果（作为对比基准）
- **用途：** 回归测试时作为 baseline
- **规则：** 只保留最新的，不要堆积

**当前基线文件：**
- `sandbox_live_check_docker_latest.json` - Docker 沙箱检查
- `step_watcher_evidence_baseline.json` - Step Watcher 基线

#### `archive/` - 历史归档
- **存放：** 过时的评测快照（按季度归档）
- **用途：** 历史追溯、证据保留
- **规则：** 按季度归档，超过1年可以删除

---

## ✅ DO：推荐做法

### 1. 更新 baseline
```bash
# 跑完评测后，如果这是新的 baseline：

# 1. 归档旧的
mkdir -p docs/testing/baselines/archive/2026-q4
mv docs/testing/baselines/current/*.json \
   docs/testing/baselines/archive/2026-q4/

# 2. 保存新的
cp my-eval-results.json \
   docs/testing/baselines/current/capability-baseline-20261019.json
```

### 2. 定期清理归档
```bash
# 每季度归档
mkdir -p docs/testing/baselines/archive/2026-q{N}
mv docs/testing/baselines/current/*.json \
   docs/testing/baselines/archive/2026-q{N}/

# 每年删除旧归档
rm -rf docs/testing/baselines/archive/2024-*/
```

---

## ❌ DON'T：禁止做法

### 1. ❌ 不要在 current/ 堆积历史快照
```bash
# ❌ 错误：current/ 有多个历史快照
current/
├── capability-baseline-20260713.json
├── capability-baseline-20260815.json
└── capability-baseline-20261019.json

# ✅ 正确：只保留最新的
current/
└── capability-baseline-20261019.json

archive/2026-q3/
├── capability-baseline-20260713.json
└── capability-baseline-20260815.json
```

### 2. ❌ 不要混淆"框架定义"和"评测结果"
```bash
# ❌ 错误
frameworks/
└── evaluation-results-20261019.json   # 这是结果，不是框架

# ✅ 正确
frameworks/
└── capability-scoring.md              # 框架定义

baselines/current/
└── capability-baseline-20261019.json  # 评测结果
```

### 3. ❌ 不要提交临时评测结果
```bash
# 临时测试结果不要放在 docs/
# 放在 artifacts/ 或本地即可
./artifacts/test-run-20261019.json
```

---

## 🔄 工作流程

### 场景 1: 我跑了一次评测

**如果这是新的 baseline：**
1. 归档旧的 → `archive/2026-qX/`
2. 保存新的 → `current/`
3. 提交到 Git

**如果只是临时测试：**
1. 不要提交到 docs/
2. 放在 artifacts/ 或本地

### 场景 2: 我要做回归测试

```bash
# 1. 跑新的评测
python scripts/eval/run_capability_eval.py --out artifacts/new-result.json

# 2. 对比 baseline
python scripts/eval/compare_baseline.py \
  --baseline docs/testing/baselines/current/capability-baseline.json \
  --current artifacts/new-result.json

# 3. 查看结果
# - regression_detected: True → 有退化，不要合并
# - regression_detected: False → 无退化，可以合并
```

---

## 📚 相关文档

- [文档贡献指南](../CONTRIBUTING_DOCS.md) - 了解文档规则
- [失败回归管道](../operations/failure-regression.md) - 回归门禁流程
- [文档导航](../README.md) - 返回文档首页

---

**维护：** 项目维护团队  
**更新：** 2026-10-20
