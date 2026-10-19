# 工作流改进 - 快速参考

## 新增工具

### 1. workflow_helper.py - 工作流引导工具
```bash
# 查看所有可用工作流
python scripts/workflow_helper.py --workflow list

# 引导式 Spec 更新（推荐新手使用）
python scripts/workflow_helper.py --workflow spec-update --direction harness

# 检查进度
python scripts/workflow_helper.py --workflow status

# PR 就绪检查清单
python scripts/workflow_helper.py --workflow pr-ready
```

### 2. spec_workflow.py update - 安全更新进度
```bash
# 更新验收项状态
python .codex/skills/spec-progress-workflow/scripts/spec_workflow.py update \
  --direction harness \
  --stage P3 \
  --acceptance P3-2 \
  --acceptance-status complete \
  --note "Your note here"

# 更新阶段状态
python .codex/skills/spec-progress-workflow/scripts/spec_workflow.py update \
  --direction harness \
  --stage P3 \
  --stage-status in_progress
```

### 3. gate_formatter.py - 友好的门禁输出
```bash
# 格式化输出（推荐）
python scripts/ci/gate_formatter.py --stage P3

# 原始输出
python scripts/ci/gate_formatter.py --stage P3 --raw
```

## 推荐工作流

### Spec 更新标准流程
```bash
# 1. 使用引导工具（可选但推荐）
python scripts/workflow_helper.py --workflow spec-update --direction harness

# 或手动执行：

# 1a. 检查当前状态
python .codex/skills/spec-progress-workflow/scripts/spec_workflow.py status --direction harness

# 2. 阅读必需文档
# - docs/spec/constraints.md
# - docs/spec/goals/harness.md
# - progress.yaml

# 3. 做你的代码修改
# ... 编辑文件 ...

# 4. 更新进度（使用工具，不要手工编辑）
python .codex/skills/spec-progress-workflow/scripts/spec_workflow.py update \
  --direction harness --stage P3 --acceptance P3-2 --acceptance-status complete

# 5. 验证配置
python .codex/skills/spec-progress-workflow/scripts/spec_workflow.py validate

# 6. 运行门禁（使用格式化输出）
python scripts/ci/gate_formatter.py --stage P3

# 7. PR 就绪检查
python scripts/ci/check_pr_ready.py
```

## 关键改进

✅ **发现性**: workflow_helper 引导你完成正确流程  
✅ **安全性**: spec_workflow.py update 自动验证，防止错误  
✅ **可读性**: gate_formatter 清晰显示状态和下一步  
✅ **效率**: 一条命令完成更新，无需手工编辑  

详见: `docs/WORKFLOW_IMPROVEMENTS.md`
