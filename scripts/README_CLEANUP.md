# 临时文件清理工具

## 快速使用

### Windows (PowerShell)
```powershell
# 查看将要删除的内容
.\cleanup.ps1 -DryRun

# 清理所有临时文件
.\cleanup.ps1

# 仅清理根目录，保留 .cache
.\cleanup.ps1 -KeepCache
```

### Linux/Mac (Bash)
```bash
# 使用 Python 脚本
python scripts/cleanup_temp.py --dry-run
python scripts/cleanup_temp.py
python scripts/cleanup_temp.py --keep-cache

# 或使用 Make
make clean-temp
make clean
```

## 集成到工作流

### 测试前清理
```powershell
.\cleanup.ps1 -KeepCache
pytest tests/
```

### 测试后自动清理
```powershell
pytest tests/; .\cleanup.ps1 -KeepCache
```

### Git commit 前检查
```bash
git status --short
# 如果看到临时目录，运行：
.\cleanup.ps1
```

## 临时目录类型

- `.pytest-tmp-*` - pytest 创建的临时测试目录
- `.tmp-pr*-*` - PR 验收相关的临时文件
- `.release-*` - 发布流程的临时文件
- `.evidence_tmp` - 证据收集的临时文件
- `.pytest-basetemp` - pytest 基础临时目录

## 未来所有临时文件位置

根据新的配置，所有临时文件将统一存放在：
```
.cache/tmp/
├── pytest/
├── evidence/
├── pr{number}/
└── release-{id}/
```

## 相关文档

详细说明请参考：`docs/TEMP_DIR_MANAGEMENT.md`
