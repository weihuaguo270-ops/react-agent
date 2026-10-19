# Pre-PR 工作流工具使用指南

## 快速参考

### 每次提交 PR 前执行
```bash
# 完整检查
python scripts/ci/pre_pr_check.py

# 快速检查（跳过慢速测试）
python scripts/ci/pre_pr_check.py --quick

# 自动修复
python scripts/ci/pre_pr_check.py --fix
```

---

## 工具说明

### 1. `pre_pr_check.py` - PR 提交前检查工具

**功能**：
- ✅ 检查 Git 状态（是否有未提交更改）
- ✅ 检查 Conventional Commit 格式
- ✅ 检查尾随空格
- ✅ 检查未跟踪的文档文件
- ✅ 检查 git-docs baseline 是否最新
- ✅ 运行 Lint 检查
- ✅ 运行核心测试

**输出示例**：
```
======================================================================
Pre-PR Submission Checks
======================================================================

Checking: Git Status... ✓ PASS
Checking: Conventional Commit... ✓ PASS
Checking: Trailing Whitespace... ✓ PASS
Checking: Untracked Docs... ✗ FAIL
  Found 5 untracked doc files:
    - docs/NEW_DOC.md
  Fix suggestion: git add docs/*.md  # or: git clean -fd docs/

Checking: Git-Docs Baseline... ✗ FAIL
  Baseline out of sync with current docs corpus
  Fix suggestion: python scripts/eval/docs/run_git_docs_eval.py --refresh-baseline

======================================================================
Summary: 3/5 checks passed
======================================================================
```

---

## 完整工作流示例

### 场景：完成 P3 功能，准备提交 PR

```bash
# 1. 开发完成，提交代码
git add src/react_agent/eval/report.py
git add tests/evaluation/test_eval_runner_episode_integration.py
git commit -m "feat(eval): add EvaluationEpisode generation to EvalRunner"

# 2. 清理未跟踪的临时文档
git clean -fdn docs/  # 预览
git clean -fd docs/   # 执行清理

# 3. 刷新 baseline（如果文档有变化）
python scripts/eval/docs/run_git_docs_eval.py --refresh-baseline

# 4. 如果 baseline 改变，提交它
git add src/react_agent/apps/docs_troubleshoot/git_docs_corpus_baseline.json
git commit -m "chore: refresh git-docs baseline"

# 5. 运行 pre-PR 检查
python scripts/ci/pre_pr_check.py

# 6. 如果通过，推送
git push -u origin feat/p3-evaluation-convergence

# 7. 创建 PR
gh pr create --title "feat(eval): complete P3 Evaluation Convergence" \
  --body "$(cat .github/PULL_REQUEST_TEMPLATE.md)"

# 8. 监控 CI
gh pr checks 153
```

---

## 常见问题和解决方案

### Q1: Git-Docs Baseline 总是失败？

**原因**：本地有未跟踪的文档文件

**解决**：
```bash
# 方案 A: 清理
git clean -fd docs/
python scripts/eval/docs/run_git_docs_eval.py --refresh-baseline

# 方案 B: 提交这些文档
git add docs/*.md
git commit -m "docs: add new documentation"
python scripts/eval/docs/run_git_docs_eval.py --refresh-baseline
```

### Q2: Conventional Commit 格式不对？

**常用格式**：
```bash
feat: 新功能
fix: 修复
docs: 文档
chore: 构建/工具
refactor: 重构
test: 测试
perf: 性能
style: 格式

# 修正
git commit --amend -m "feat: your message"
```

### Q3: 核心测试失败？

**调试**：
```bash
# 运行单个测试
pytest tests/evaluation/test_eval_runner_episode_integration.py -xvs

# 查看详细输出
pytest tests/ -x --tb=short
```

---

## 自动化设置

### Git Hooks（可选）

#### Pre-commit Hook
```bash
# 创建 .git/hooks/pre-commit
cat > .git/hooks/pre-commit << 'EOF'
#!/bin/bash
python scripts/ci/pre_pr_check.py --quick
EOF

chmod +x .git/hooks/pre-commit
```

#### Pre-push Hook
```bash
# 创建 .git/hooks/pre-push
cat > .git/hooks/pre-push << 'EOF'
#!/bin/bash
python scripts/ci/pre_pr_check.py
EOF

chmod +x .git/hooks/pre-push
```

---

## 文件清单

本次创建的工作流工具：

1. **`scripts/ci/pre_pr_check.py`** (主工具)
   - 自动化检查脚本
   - 支持 --fix 自动修复
   - 支持 --quick 快速模式

2. **`scripts/ci/WORKFLOW_CI_BEST_PRACTICES.md`** (详细文档)
   - CI 失败原因分析
   - 完整解决方案
   - 最佳实践指南

3. **本文件** - 快速参考指南

---

## 下一步改进建议

1. **集成到 AGENTS.md**
   - 添加工作流说明
   - 引导新贡献者使用

2. **创建 VS Code Task**
   - 一键运行检查
   - IDE 集成

3. **添加到 CI**
   - PR 模板中提示使用
   - 自动评论失败原因

4. **收集反馈**
   - 使用几次后优化
   - 添加更多检查项

---

## 总结

**核心价值**：
- ⏱️ 节省时间：本地发现问题，不等 CI
- 🔒 提高质量：强制检查规范
- 📚 知识沉淀：文档化最佳实践
- 🔄 可持续：可复用的工作流

**使用建议**：
- 每次提交 PR 前运行
- 遇到 CI 失败时参考文档
- 定期更新检查项

---

**创建日期**: 2026-10-19
**版本**: 1.0
**维护者**: 工作流改进小组
