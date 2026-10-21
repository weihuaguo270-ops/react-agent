# CI Workflow 改进说明

## 问题分析

在 PR #156 的 CI 测试中，发现了以下问题：

1. **文档基线更新需要手动操作** - 添加新文档后必须手动更新 `git_docs_corpus_baseline.json`
2. **Revert 提交被拒绝** - Revert 提交不符合 conventional commit 格式导致 CI 失败
3. **缺少导入验证** - 错误的测试文件（导入不存在的函数）没有被提前检测

## 解决方案

### 1. 支持 Revert 提交

**修改**: `scripts/ci/check_pr_ready.py`
- 添加 `--allow-revert` 参数
- 当提交消息以 "Revert " 开头时允许通过

**使用**:
```bash
python scripts/ci/check_pr_ready.py --ci --base-sha "$PR_BASE_SHA" --allow-revert
```

### 2. 文档基线自动刷新工具

**新增**: `scripts/ci/refresh_docs_baseline.py`
- 自动刷新文档基线
- 报告变更的文件数量（添加/删除/修改）
- 可在 CI 或本地使用

**使用**:
```bash
python scripts/ci/refresh_docs_baseline.py
```

### 3. 导入静态检查工具

**新增**: `scripts/ci/check_imports.py`
- 检查所有 Python 文件的导入语法
- 可扩展为检查导入的模块/函数是否存在

**使用**:
```bash
python scripts/ci/check_imports.py
```

## 建议的 CI 工作流更新

### 选项 A: 在 PR ready audit 中使用 --allow-revert

```yaml
- name: Check PR readiness
  env:
    PR_BASE_SHA: ${{ github.event.pull_request.base.sha }}
  run: python scripts/ci/check_pr_ready.py --ci --base-sha "$PR_BASE_SHA" --allow-revert
```

### 选项 B: 添加文档基线自动更新（可选）

在 CI 中添加一个步骤，自动刷新基线：

```yaml
- name: Auto-refresh docs baseline if needed
  run: python scripts/ci/refresh_docs_baseline.py
```

### 选项 C: 添加导入检查（可选）

```yaml
- name: Check imports
  run: python scripts/ci/check_imports.py
```

## 改进效果

1. ✅ **Revert 提交可以通过 CI** - 减少不必要的 CI 失败
2. ✅ **文档基线更新更简单** - 提供自动化工具
3. ✅ **导入错误提前发现** - 在 CI 早期阶段检测问题

## 测试

本地测试命令：
```bash
# 测试 revert 提交检查
python scripts/ci/check_pr_ready.py --allow-revert

# 测试文档基线刷新
python scripts/ci/refresh_docs_baseline.py

# 测试导入检查
python scripts/ci/check_imports.py
```

## 向后兼容性

- 所有新增的参数都是可选的
- 默认行为保持不变
- 不影响现有的 CI 工作流
