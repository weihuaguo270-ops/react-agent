# CI Best Practices and Pre-PR Workflow

## 概述

本文档记录了在提交 PR 到 GitHub 之前应该执行的检查流程，以确保 CI 顺利通过。

---

## 快速开始

### 提交 PR 前执行

```bash
# 完整检查
python scripts/ci/pre_pr_check.py

# 快速检查（跳过慢速测试）
python scripts/ci/pre_pr_check.py --quick

# 自动修复可修复的问题
python scripts/ci/pre_pr_check.py --fix
```

---

## 常见 CI 失败原因和解决方案

### 1. ❌ PR Ready Audit 失败

#### 原因
- HEAD commit 不符合 conventional commit 格式
- 有未提交的更改
- 存在尾随空格

#### 解决方案
```bash
# 检查 commit 格式
git log -1 --pretty=%s

# 修正 commit message（如果不符合规范）
git commit --amend -m "feat: your feature description"
# 或
git commit --amend -m "fix: your bug fix description"

# Conventional commit 类型：
# feat: 新功能
# fix: 修复
# docs: 文档
# style: 格式
# refactor: 重构
# perf: 性能优化
# test: 测试
# chore: 构建/工具

# 检查尾随空格
git diff --check HEAD
```

---

### 2. ❌ Git-Docs Corpus Drift 测试失败

#### 原因
本地有**未跟踪的文档文件**，导致 baseline 与 CI 环境不匹配。

#### 现象
```
FAILED tests/test_git_docs_corpus_drift.py::test_drift_clean_when_matching_baseline
AssertionError: corpus status is 'changed', expected 'clean'
```

#### 根本原因
1. 本地 `docs/` 目录有未跟踪（untracked）的 .md 文件
2. 运行 `--refresh-baseline` 时，这些文件被包含在 baseline 中
3. CI 环境没有这些文件（因为未提交），导致 baseline 不匹配

#### 解决方案

**方案 A: 清理未跟踪文件（推荐）**
```bash
# 1. 预览将被删除的文件
git clean -fdn docs/

# 2. 确认后清理
git clean -fd docs/

# 3. 刷新 baseline
python scripts/eval/docs/run_git_docs_eval.py --refresh-baseline

# 4. 验证
pytest tests/test_git_docs_corpus_drift.py::test_drift_clean_when_matching_baseline -xvs

# 5. 提交更新的 baseline
git add src/react_agent/apps/docs_troubleshoot/git_docs_corpus_baseline.json
git commit -m "chore: refresh git-docs baseline"
```

**方案 B: 提交未跟踪的文档**
```bash
# 1. 查看未跟踪的文档
git status | grep "docs/.*\.md"

# 2. 添加需要的文档
git add docs/YOUR_NEW_DOC.md

# 3. 提交
git commit -m "docs: add YOUR_NEW_DOC documentation"

# 4. 刷新 baseline
python scripts/eval/docs/run_git_docs_eval.py --refresh-baseline

# 5. 提交 baseline
git add src/react_agent/apps/docs_troubleshoot/git_docs_corpus_baseline.json
git commit -m "chore: refresh git-docs baseline"
```

---

### 3. ❌ 测试失败

#### 解决方案
```bash
# 运行失败的测试
pytest tests/test_name.py -xvs

# 运行所有测试
pytest tests/ -x

# 只运行 P3 相关测试
pytest tests/evaluation/test_execution_episode_integration.py -v
pytest tests/evaluation/test_eval_runner_episode_integration.py -v
```

---

### 4. ❌ Lint 失败

#### 解决方案
```bash
# 检查 lint 问题
ruff check src/ tests/

# 自动修复
ruff check --fix src/ tests/

# Typecheck
mypy src/
```

---

## 完整 PR 提交工作流

### 步骤 1: 本地开发完成

```bash
# 确保在正确的分支
git branch

# 查看更改
git status
git diff
```

### 步骤 2: 提交更改

```bash
# 添加文件
git add <files>

# 提交（使用 conventional commit 格式）
git commit -m "feat: add P3 evaluation episode integration"
```

### 步骤 3: 清理环境

```bash
# 清理未跟踪的 docs 文件
git clean -fdn docs/  # 预览
git clean -fd docs/   # 执行

# 清理其他未跟踪文件（谨慎）
git clean -fdn
git clean -fd
```

### 步骤 4: 刷新 Baseline

```bash
# 刷新 git-docs baseline
python scripts/eval/docs/run_git_docs_eval.py --refresh-baseline

# 如果 baseline 有变化，提交它
git add src/react_agent/apps/docs_troubleshoot/git_docs_corpus_baseline.json
git commit -m "chore: refresh git-docs baseline"
```

### 步骤 5: 运行 Pre-PR 检查

```bash
# 完整检查
python scripts/ci/pre_pr_check.py

# 或带自动修复
python scripts/ci/pre_pr_check.py --fix
```

### 步骤 6: 推送和创建 PR

```bash
# 推送到远程
git push -u origin feature/your-branch

# 创建 PR（使用 gh CLI）
gh pr create --title "feat: your feature" --body "description"

# 或通过 URL
# GitHub 会在推送后显示 PR 创建链接
```

### 步骤 7: 监控 CI

```bash
# 检查 CI 状态
gh pr checks <PR_NUMBER>

# 查看 PR 详情
gh pr view <PR_NUMBER>

# 查看失败的日志
gh run view <RUN_ID> --log-failed
```

---

## Git-Docs Baseline 详解

### 什么是 git-docs baseline？

`git_docs_corpus_baseline.json` 记录了 `docs/` 目录中所有文档文件的 SHA256 哈希值。
这用于检测文档内容的变化，因为 git-docs 评测依赖文档内容作为 RAG 语料。

### 为什么需要刷新？

当你：
1. 添加新文档
2. 修改现有文档
3. 删除文档

文档语料发生变化，需要更新 baseline。

### 如何判断需要刷新？

```bash
# 运行 drift 检测测试
pytest tests/test_git_docs_corpus_drift.py -xvs

# 如果失败，说明需要刷新
```

### 刷新 Baseline 的最佳实践

```bash
# 1. 确保只有需要的文档被 git 跟踪
git status

# 2. 清理未跟踪的临时文档
git clean -fd docs/

# 3. 刷新 baseline
python scripts/eval/docs/run_git_docs_eval.py --refresh-baseline

# 4. 验证刷新成功
pytest tests/test_git_docs_corpus_drift.py::test_drift_clean_when_matching_baseline -xvs

# 5. 提交 baseline
git add src/react_agent/apps/docs_troubleshoot/git_docs_corpus_baseline.json
git commit -m "chore: refresh git-docs baseline after docs changes"
```

---

## 自动化建议

### 1. Pre-commit Hook

创建 `.git/hooks/pre-commit`:

```bash
#!/bin/bash
# Pre-commit hook to run quick checks

python scripts/ci/pre_pr_check.py --quick

if [ $? -ne 0 ]; then
    echo "Pre-commit checks failed. Use --no-verify to skip."
    exit 1
fi
```

### 2. Pre-push Hook

创建 `.git/hooks/pre-push`:

```bash
#!/bin/bash
# Pre-push hook to run full checks

python scripts/ci/pre_pr_check.py

if [ $? -ne 0 ]; then
    echo "Pre-push checks failed. Use --no-verify to skip."
    exit 1
fi
```

### 3. IDE 集成 (VS Code)

在 `.vscode/tasks.json` 添加：

```json
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "Pre-PR Check",
      "type": "shell",
      "command": "python scripts/ci/pre_pr_check.py",
      "group": {
        "kind": "test",
        "isDefault": true
      },
      "presentation": {
        "reveal": "always",
        "panel": "new"
      }
    }
  ]
}
```

---

## 问题排查 Checklist

在 CI 失败时，按顺序检查：

- [ ] HEAD commit 是否符合 conventional commit 格式？
- [ ] 是否有未提交的更改？
- [ ] `docs/` 是否有未跟踪的文件？
- [ ] git-docs baseline 是否是最新的？
- [ ] 本地测试是否全部通过？
- [ ] 是否有尾随空格？
- [ ] Lint/typecheck 是否通过？

---

## 相关命令速查

```bash
# Git 状态
git status --short
git log -1 --pretty=%s

# 清理
git clean -fdn          # 预览清理
git clean -fd           # 清理未跟踪文件

# 未跟踪文件
git ls-files --others --exclude-standard

# Baseline
python scripts/eval/docs/run_git_docs_eval.py --refresh-baseline

# 测试
pytest tests/test_git_docs_corpus_drift.py -xvs
pytest tests/ -x

# Lint
ruff check src/ tests/
ruff check --fix src/ tests/

# PR 管理
gh pr create
gh pr checks <NUMBER>
gh pr view <NUMBER>
```

---

## 总结

**核心原则**：
1. 提交前清理未跟踪文件
2. 文档变化后刷新 baseline
3. 本地验证后再推送
4. 使用 conventional commit 格式

**工具**：
- `scripts/ci/pre_pr_check.py` - 自动化检查
- `git clean -fd docs/` - 清理未跟踪文档
- `--refresh-baseline` - 更新文档 baseline

遵循这个工作流可以避免 90% 的 CI 失败！
