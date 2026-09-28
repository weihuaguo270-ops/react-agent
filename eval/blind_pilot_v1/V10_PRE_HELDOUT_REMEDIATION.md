# v10 held-out 前整改记录（2026-09-22）

整改已完成：

1. Pydantic 历史运行已后补 `patch_status=verified_fix`、`patch_bytes=1415`、`patch_sha256=6d2e7734b181b2233af0202b8ec35c096657959320e5d1bd181fe198ddf16dfc`，并标记 `patch_fields_source=posthoc_offline_verification`、`patch_fields_original_run=false`。
2. submit-only 探针 `scripts/probe_submit_tool_choice.py` 使用冻结模型和兼容服务、只暴露 submit、`tool_choice=required`，返回单个 submit，`valid=true`，total tokens 335。探针不读取仓库、不运行任务。
3. 四条 development 的 hidden 结果均通过；Pydantic 使用后补字段，其余三条使用原始运行字段。主动提交仍为 1/4，控制器终态不计入主动提交。

本记录只证明整改当前通过，不改变 v6-v10 历史成绩。由于 development 曾出现跨任务终态工具选择异常，held-out 仍需单独决策；golden 保持 0。
