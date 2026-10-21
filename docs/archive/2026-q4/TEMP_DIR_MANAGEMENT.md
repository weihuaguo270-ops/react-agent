# 临时目录管理

## 问题

项目运行测试和验收时会在根目录产生大量临时文件：
- `.pytest-tmp-*` (多个带 PID 的目录)
- `.tmp-pr*-*`
- `.release-*`
- `.evidence_tmp`
- `.pytest-basetemp`

这些文件污染根目录，且容易被误提交。

## 解决方案

### 1. 集中化策略

**所有临时文件统一存放在 `.cache/tmp/` 目录下**，按类型分子目录：

```
.cache/
└── tmp/
    ├── pytest/          # pytest 临时文件
    ├── evidence/        # 证据临时文件
    ├── pr{number}/      # PR 相关临时文件
    └── release-{id}/    # 发布临时文件
```

### 2. 配置更改

#### pyproject.toml
```toml
[tool.pytest.ini_options]
cache_dir = ".cache/pytest"
tmp_path_retention_count = 1
tmp_path_retention_policy = "failed"
```

#### tests/conftest.py
自动配置 pytest 使用集中的临时目录（已添加 `configure_temp_dirs` fixture）。

#### 代码使用
```python
from react_agent.temp_dirs import (
    get_temp_dir,
    get_pytest_temp_dir,
    get_evidence_temp_dir,
    get_pr_temp_dir,
    cleanup_temp_dirs,
)

# 获取临时目录
temp_dir = get_evidence_temp_dir()

# 清理旧的临时目录（保留最近 1 个）
cleanup_temp_dirs(keep_recent=1)
```

### 3. 清理命令

#### 手动清理
```bash
# 查看将要删除的内容（dry-run）
python scripts/cleanup_temp.py --dry-run

# 清理所有临时目录
python scripts/cleanup_temp.py

# 仅清理根目录的临时文件，保留 .cache/tmp/
python scripts/cleanup_temp.py --keep-cache
```

#### Git hooks（可选）
复制 `.git/hooks/pre-commit.sample` 为 `.git/hooks/pre-commit` 并添加执行权限，
可以防止意外提交临时目录。

### 4. .gitignore 更新

已添加以下忽略规则：
```gitignore
.pytest-tmp*/
.pytest-basetemp/
.tmp/
.tmp-*/
.evidence_tmp/
.release-*/
.cache/tmp/
```

## 迁移指南

### 现有代码修改

如果代码中有硬编码的临时路径，应替换为统一的 API：

**之前：**
```python
temp_dir = Path(".evidence_tmp")
temp_dir.mkdir(exist_ok=True)
```

**之后：**
```python
from react_agent.temp_dirs import get_evidence_temp_dir
temp_dir = get_evidence_temp_dir()
```

### 清理现有临时文件

```bash
# 1. 先用 dry-run 检查
python scripts/cleanup_temp.py --dry-run

# 2. 确认后执行清理
python scripts/cleanup_temp.py

# 3. 验证 git status 干净
git status --short
```

## 最佳实践

1. **永远不要在根目录创建临时文件** - 使用 `temp_dirs.get_temp_dir()`
2. **测试后自动清理** - 在 CI 中添加清理步骤
3. **定期清理** - 开发时运行 `cleanup_temp.py` 清理旧文件
4. **提交前检查** - 运行 `git status` 确保没有临时文件

## CI 集成

在 `.github/workflows/test.yml` 中添加清理步骤：

```yaml
- name: Cleanup temp directories
  if: always()
  run: python scripts/cleanup_temp.py
```

## 故障排查

### 问题：临时目录仍在根目录生成

**检查项：**
1. 确认代码使用了 `react_agent.temp_dirs` API
2. 检查是否有硬编码路径：`grep -r "\.pytest-tmp\|\.evidence_tmp" src/`
3. 验证 pytest 配置：`pytest --version && pytest --co -q`

### 问题：.cache/tmp/ 目录过大

**解决方案：**
```bash
# 保留最近 1 个，删除其余
python -c "from react_agent.temp_dirs import cleanup_temp_dirs; cleanup_temp_dirs(keep_recent=1)"

# 或手动删除整个目录
rm -rf .cache/tmp/
```

## 相关文件

- `src/react_agent/temp_dirs.py` - 统一临时目录 API
- `scripts/cleanup_temp.py` - 清理脚本
- `tests/conftest.py` - pytest 配置
- `.gitignore` - Git 忽略规则
