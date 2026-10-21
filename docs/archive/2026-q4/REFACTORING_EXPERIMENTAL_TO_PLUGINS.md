# 从"实验功能"到"插件系统"的重构

## 概述

将项目中的"Experimental Features"重命名为"Plugins"，更准确地反映这些功能的性质。

## 重构原因

### "实验功能"命名的问题
1. ❌ **暗示不稳定** - 让人觉得功能可能随时被移除
2. ❌ **暗示不可用于生产** - 实际上 RAG 和 Multi-Agent 已经成熟
3. ❌ **混淆概念** - 把"可选"和"实验性"混为一谈
4. ❌ **降低信任度** - 用户可能不敢在正式项目使用

### "插件"命名的优势
1. ✅ **准确描述** - 这些是可选的扩展功能
2. ✅ **中性表述** - 不暗示质量或稳定性问题
3. ✅ **行业标准** - 符合插件化架构的通用概念
4. ✅ **灵活控制** - 支持选择性启用特定插件

## 重构范围

### 1. 环境变量重命名

**新变量（推荐）:**
```bash
REACT_AGENT_PLUGINS=1                    # 启用所有插件
REACT_AGENT_PLUGINS=rag,mcp,orchestration # 启用特定插件
```

**旧变量（兼容6-12个月）:**
```bash
REACT_AGENT_EXPERIMENTAL_TOOLS=1  # Deprecated，但仍有效
```

### 2. 文件和目录重命名

| 旧名称 | 新名称 | 状态 |
|--------|--------|------|
| `docs/EXPERIMENTAL.md` | `docs/PLUGINS.md` | ✅ 已创建 |
| `tests/experimental/` | `tests/plugins/` | 待重命名 |
| `tests/experimental/README.md` | `tests/plugins/README.md` | 待更新 |

### 3. 代码更新

**需要更新的文件:**
- `src/react_agent/tools/__init__.py` - 环境变量检查逻辑
- `src/react_agent/harness/sandbox.py` - 环境变量传递
- `src/react_agent/react_loop.py` - 注释更新
- 各个文档中的引用

### 4. 文档更新

**需要更新的文档:**
- `README.md` - 更新插件说明
- `docs/STRUCTURE.md` - 更新模块清单
- `docs/CORE_ARCHITECTURE.md` - 更新术语
- `docs/AGENT_WORKFLOW.md` - 更新引用
- `docs/APPLICATION_DIRECTION.md` - 更新配置示例

## 实施计划

### Phase 1: 新增插件文档 ✅
- [x] 创建 `docs/PLUGINS.md`
- [x] 包含完整的插件说明和配置指南
- [x] 说明向后兼容策略

### Phase 2: 代码重构（保持向后兼容）
- [ ] 更新 `src/react_agent/tools/__init__.py`
  - 添加 `REACT_AGENT_PLUGINS` 支持
  - 保留 `REACT_AGENT_EXPERIMENTAL_TOOLS` 兼容
  - 添加 deprecation 警告
- [ ] 更新其他源代码文件中的引用
- [ ] 更新注释和文档字符串

### Phase 3: 测试重构
- [ ] 重命名 `tests/experimental/` → `tests/plugins/`
- [ ] 更新测试文档
- [ ] 更新测试中的环境变量

### Phase 4: 文档全面更新
- [ ] 更新所有文档中的"experimental"引用
- [ ] 添加迁移指南
- [ ] 更新 README 和 CHANGELOG

### Phase 5: 清理（6-12个月后）
- [ ] 移除旧环境变量支持
- [ ] 移除 deprecation 警告
- [ ] 更新文档移除兼容性说明

## 向后兼容策略

### 环境变量兼容
```python
def is_plugins_enabled():
    """检查插件是否启用（支持新旧变量）"""
    # 新变量优先
    plugins = os.environ.get("REACT_AGENT_PLUGINS", "").strip()
    if plugins:
        if plugins.lower() in ("1", "true", "yes", "on"):
            return True
        return plugins  # 返回插件列表
    
    # 向后兼容旧变量
    legacy = os.environ.get("REACT_AGENT_EXPERIMENTAL_TOOLS", "").strip()
    if legacy.lower() in ("1", "true", "yes", "on"):
        warnings.warn(
            "REACT_AGENT_EXPERIMENTAL_TOOLS is deprecated. "
            "Use REACT_AGENT_PLUGINS instead.",
            DeprecationWarning,
            stacklevel=2
        )
        return True
    
    return False
```

### 文档兼容
- 保留 `docs/EXPERIMENTAL.md`，内容重定向到 `docs/PLUGINS.md`
- 在文档中添加"此术语已更新"的提示

## 受益者

1. **新用户** - 不会误解这些功能的成熟度
2. **现有用户** - 向后兼容，无需立即修改配置
3. **文档维护者** - 术语更准确，减少混淆
4. **项目形象** - 更专业的命名提升项目可信度

## 术语对照

| 旧术语 | 新术语 |
|--------|--------|
| Experimental Features | Plugins |
| Experimental Module | Plugin |
| Enable Experimental | Enable Plugins |
| EXPERIMENTAL_TOOLS | PLUGINS |
| tests/experimental/ | tests/plugins/ |

## 风险评估

### 低风险
- ✅ 向后兼容保证现有用户不受影响
- ✅ 仅涉及命名，不改变功能实现
- ✅ 文档更新不影响代码运行

### 需要注意
- ⚠️ 确保所有文档都更新到位
- ⚠️ CI/CD 配置可能需要更新环境变量
- ⚠️ 社区文章、教程可能还在用旧术语

## 成功标准

1. ✅ 新文档 `docs/PLUGINS.md` 完整清晰
2. ⬜ 代码支持新旧环境变量
3. ⬜ 测试目录重命名完成
4. ⬜ 所有文档引用已更新
5. ⬜ deprecation 警告正常工作
6. ⬜ CI 通过所有测试

## 时间表

- **Week 1**: Phase 1-2（文档和代码重构）
- **Week 2**: Phase 3-4（测试和文档更新）
- **6-12 months**: Phase 5（清理旧代码）

## 相关链接

- 新插件文档: `docs/PLUGINS.md`
- 重构讨论: 本次对话
- 测试目录: `tests/plugins/` (待创建)
