# 首批任务覆盖审查

任务验证数量与 Agent 解题成绩分开统计。当前共 6 条 verified，golden 为 0。v6 development 已运行 4 条：隐藏验收 3/4、主动提交 1/4、预算合规 4/4；provisional held-out 未运行。详见 [v6 报告](blind_pilot_v1/DEVELOPMENT_V6_FULL_REPORT.md)。以下候选建设过程记录不代表当前待办。

| 任务 | 缺陷类型 | 覆盖限制 |
| --- | --- | --- |
| pydantic-identity-review | 类型别名与对象相等性 | 小范围类型语义 |
| httpx-identity-review | URL path 编码 | 字符边界 |
| httpx-activity-review | URL gen-delims 编码 | 与上一条同仓、同子系统，不宜跨 split |
| werkzeug-auth-whitespace-3129 | HTTP 认证头序列化 | 协议格式边界 |
| click-typed-flag-2930 | CLI 参数状态与显式类型转换 | 需证明显式类型、默认值和 flag 激活的交互；已完成两次 before、两次 after 和完整哈希校验 |
| jinja-async-unique-1782 | 异步生成器与 unique 过滤器集成 | 已完成两次 before、两次 after、独立 hidden acceptance 和完整哈希校验 |

4 条既有任务中 3 条集中在 HTTP 字符处理。第 5 条选择 Click PR #2930（issues #2894、#2897），避免再增加 URL/HTTP 格式任务。第 6 条优先寻找数据集合处理、持久化状态或构建配置缺陷。

Click 来源已保存完整 API 正文、访问时间、base/fix SHA 和两端依赖配置，并生成 source-manifest.json。Python >=3.10；Windows 运行依赖 colorama，构建依赖 flit_core<4。此为静态依赖审查，尚未证明干净环境可重建。CliRunner 可用于无外部服务的行为测试；实际离线验证待执行。

## 下一道门槛

独立环境安装固定依赖，before 两次因目标断言失败；独立验收覆盖类型、默认值、显式 flag_value 和非 flag 回归；after 两次通过。自动保存原始日志、退出码、轨迹及 SHA256，再校验晋级。来源清单哈希不能替代执行证据。

## 盲测边界

账本原有 held_out 标签暂改为 unassigned，不代表已具备独立性。最终 4/2 切分须按来源及类型分组；同源 URL 缺陷不能拆开。当前策展会话已看到修复与测试，不能作为被测 Agent 会话。干净被测会话只能挂载问题和基线源码，不能访问整个工作区、修复提交或验收目录。

满 6 条后再固定模型、提示词、工具权限、时间及 token 预算，分别报告任务验证数、Agent 通过率、回归失败、耗时及实际计费成本。此规模只支持流程试运行。

Click 已通过 11 个 CLI 场景。Jinja PR #1782 已完成固定提交上的 before/after 重复执行、独立 hidden acceptance 和证据哈希校验。
