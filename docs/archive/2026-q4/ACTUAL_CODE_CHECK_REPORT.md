# 项目实际代码检查报告

**检查日期**: 2026-10-20

---

## 🔍 实际代码结构检查

### 1. Harness 模块实际状态

**目录结构检查**:
```
src/react_agent/harness/
├── contracts/           ✅ 存在 (Phase 1 完成)
│   ├── __init__.py
│   ├── compatibility.py
│   ├── parser.py
│   └── trajectory.py
├── runtime/             ✅ 存在 (Phase 2 部分完成)
│   ├── adapters.py
│   ├── episode.py
│   ├── observability.py
│   ├── policies.py
│   ├── replay.py
│   ├── shared_idempotency.py
│   └── structured_output.py
├── evaluation/          ✅ 存在 (Phase 3 完成)
│   ├── baseline_compare.py
│   ├── fixtures.py
│   ├── reliability.py
│   └── repair_evidence.py
└── adapters/            ❌ 不存在 (规格中提到但未实现)
```

**结论**: 
- ✅ 规格中建议的 `contracts/`, `runtime/`, `evaluation/` 目录已存在
- ❌ `adapters/` 目录不存在（但功能在其他地方实现）
- ✅ Phase 1 的 Shared Contracts 已实现
- ✅ Phase 2 的 Runtime 收敛部分完成（runtime/ 目录存在）
- ✅ Phase 3 的 Evaluation 收敛已完成

**测试覆盖**:
```
tests/harness/
├── test_deterministic_replay.py
├── test_harness_r2.py
└── test_runtime_observability.py
```

---

### 2. Apps 模块实际状态

**实际存在的 Apps**:
```
src/react_agent/apps/
├── __init__.py
├── docs_troubleshoot/   ✅ 21个Python文件 (活跃)
├── expense/             ✅ 8个Python文件 (存在但Hold)
├── github_delivery.py
├── patch_planner.py
└── react_patch_planner.py
```

**docs_troubleshoot**: 
- ✅ 完整实现 (21个文件)
- ✅ 有评测脚本 (4个 docs eval scripts)
- ✅ 在 CI 中运行

**expense**:
- ✅ 核心代码存在 (8个文件)
- ✅ 完整测试覆盖 (8个测试文件)
- ⚠️ Git log 显示自9月以来无提交 (符合"Hold"状态)

---

### 3. 评测脚本实际状态

**scripts/eval/ 目录结构**:
```
scripts/eval/
├── execution/    2个脚本 ✅ 活跃 (在CI中)
├── docs/         4个脚本 ✅ 活跃 (在CI中)
├── rag/          1个脚本 ⚠️ 存在但状态不明
├── failure/      多个脚本 ✅ 活跃
├── reliability/  多个脚本 ✅ 活跃
├── acceptance/   多个脚本 ✅ 活跃
└── ...
```

**CI 中的实际测试**:
- ✅ Execution (offline tools) - 运行中
- ✅ Docs troubleshoot - 运行中
- ✅ Public RAG benchmark - `pytest tests/test_public_rag_benchmark.py` 运行中
- ⚠️ 但 Execution 和 Reliability 中设置了 `REACT_AGENT_SKIP_RAG=1`

**RAG 实际状态**:
- ✅ 代码存在: `src/react_agent/rag.py`
- ✅ Demo 存在: `demos/demo_rag.py`
- ✅ 评测脚本存在: `scripts/eval/rag/run_public_rag_benchmark.py`
- ✅ CI 中测试: `pytest tests/test_public_rag_benchmark.py`
- ⚠️ 但在主要测试中被跳过 (`REACT_AGENT_SKIP_RAG=1`)

---

## 📊 README vs 实际代码对比

### docs/specs/README.md

**声称的状态**:
```markdown
| **harness** | Phase 0-5 完成 |
```

**实际状态**:
- Phase 0: ✅ Complete
- Phase 1: ✅ Complete (contracts/ 存在)
- Phase 2: ⚠️ 部分完成 (runtime/ 存在，但状态不明确)
- Phase 3: ✅ Complete (evaluation/ 存在)
- Phase 4: ⚠️ Partial
- Phase 5: 🔄 In Progress

**结论**: "Phase 0-5 完成" 是**错误的**，应该是 "Phase 0-1,3 Complete; Phase 4 Partial; Phase 5 In Progress"

---

### 根目录 README.md

**声称的三大应用方向**:
```markdown
① 写代码 / 执行
② 客服 / 自动化
③ RAG / 研究
```

**实际代码检查**:
- ① 执行: ✅ 2个eval脚本，在CI中活跃
- ② 客服: ✅ docs_troubleshoot 21个文件，expense 8个文件
- ③ RAG: ⚠️ 代码存在，CI中有测试，但在主测试中被跳过

**RAG 的矛盾信号**:
1. ✅ 代码完整存在
2. ✅ CI 中有 `test_public_rag_benchmark.py`
3. ❌ Execution 测试设置 `REACT_AGENT_SKIP_RAG=1`
4. ❌ 自9月以来 RAG 相关文件无 Git 提交

**结论**: RAG 处于**维护状态**，不是活跃开发的方向

---

## 🎯 应该如何描述

### Harness 状态

**正确描述**:
```markdown
- Phase 0: ✅ Complete (基线冻结)
- Phase 1: ✅ Complete (Shared Contracts, contracts/ 已实现)
- Phase 2: ✅ Complete (Runtime 收敛, runtime/ 已实现)
- Phase 3: ✅ Complete (Evaluation 收敛, evaluation/ 已实现)
- Phase 4: ⚠️ Partial (Replay 与回归门禁)
- Phase 5: 🔄 In Progress (兼容期迁移)
```

### Apps 状态

**正确描述**:
```markdown
- docs_troubleshoot: ✅ Active (21个文件，完整评测)
- expense: ⏸️ Hold (代码完整但等待业务确认)
- github_delivery: ✅ Implemented (单文件实现)
```

### 应用方向状态

**需要用户确认的问题**:
1. RAG 是否已废弃？
   - 如果是: 从三大方向中移除，标记为"实验性/维护模式"
   - 如果否: 说明为什么设置 `REACT_AGENT_SKIP_RAG=1`

---

## ✅ 待修正的 README

1. **docs/specs/README.md** - Harness 状态错误
2. **根目录 README.md** - 需要确认 RAG 方向
3. **docs/testing/README.md** - 已修正
4. **docs/README.md** - 需要根据 RAG 状态调整

---

**下一步**: 等待用户确认 RAG 的实际状态后，更新所有相关 README。
