## 临时文件管理方案总结

### ✅ 已完成的改进

1. **创建统一的临时目录 API** (`src/react_agent/temp_dirs.py`)
   - `get_temp_dir()` - 通用临时目录
   - `get_pytest_temp_dir()` - pytest 专用
   - `get_evidence_temp_dir()` - 证据收集专用
   - `get_pr_temp_dir()` / `get_release_temp_dir()` - PR/发布专用
   - `cleanup_temp_dirs()` - 清理旧目录

2. **配置 pytest 使用集中目录** (`pyproject.toml`)
   ```toml
   cache_dir = ".cache/pytest"
   tmp_path_retention_count = 1
   tmp_path_retention_policy = "failed"
   ```

3. **修改 conftest.py** 优先使用 `.cache/tmp/pytest`

4. **更新代码中的硬编码路径**
   - `scripts/eval/failure/run_step_watcher_evidence.py`
   - `scripts/eval/smoke/build_p2_acceptance_report.py`

5. **创建清理工具**
   - `scripts/cleanup_temp.py` (跨平台 Python 脚本)
   - `cleanup.ps1` (PowerShell 脚本)
   - `Makefile` (make clean-temp)

6. **更新 .gitignore**
   - 忽略所有临时目录模式

7. **创建文档**
   - `docs/TEMP_DIR_MANAGEMENT.md` (详细说明)
   - `scripts/README_CLEANUP.md` (快速指南)

### 🎯 使用方法

#### 日常开发
```powershell
# Windows
.\cleanup.ps1

# Linux/Mac
python scripts/cleanup_temp.py
```

#### 测试前清理
```bash
make clean-temp
pytest tests/
```

#### 集成到 CI
在 `.github/workflows/test.yml` 添加：
```yaml
- name: Cleanup temp directories
  if: always()
  run: python scripts/cleanup_temp.py
```

### 📁 新的目录结构

**之前（混乱）：**
```
react-agent/
├── .pytest-tmp-12345/
├── .pytest-tmp-67890/
├── .evidence_tmp/
├── .tmp-pr136-20261014/
├── .release-p2-mainline/
└── ...根目录污染
```

**之后（清晰）：**
```
react-agent/
└── .cache/
    └── tmp/
        ├── pytest/       # 所有 pytest 临时文件
        ├── evidence/     # 证据收集临时文件
        ├── pr{number}/   # PR 相关临时文件
        └── release-{id}/ # 发布临时文件
```

### ⚙️ 工作原理

1. **pytest 配置**：通过 `pyproject.toml` 和 `conftest.py` 将所有 pytest 临时文件重定向到 `.cache/tmp/pytest`

2. **统一 API**：所有代码使用 `react_agent.temp_dirs` 模块创建临时目录，而不是硬编码路径

3. **自动清理**：通过 `tmp_path_retention_count = 1` 和 `tmp_path_retention_policy = "failed"`，pytest 自动保留最近 1 次的失败测试临时文件

4. **Git 忽略**：`.gitignore` 包含所有临时目录模式，防止误提交

### ⚠️ 注意事项

1. **渐进式迁移**：现有代码中可能还有其他硬编码路径，遇到时应使用 `temp_dirs` API 替换

2. **清理频率**：建议每次 PR 前运行 `cleanup.ps1`，CI 中每次运行后自动清理

3. **保留策略**：pytest 只保留失败测试的临时文件，成功的会自动删除

### 🔍 检查硬编码路径

如果发现新的临时目录，运行：
```bash
grep -r "\.pytest-tmp\|\.evidence_tmp\|\.tmp-pr\|\.release-" --include="*.py" src/ scripts/
```

然后用 `temp_dirs` API 替换。

---

完整文档：`docs/TEMP_DIR_MANAGEMENT.md`
