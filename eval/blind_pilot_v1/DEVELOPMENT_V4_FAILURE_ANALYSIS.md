# Development v4 Failure Analysis

日期：2026-09-19

本分析覆盖 v4 首轮和补跑。状态来自 provider-reported total tokens 与隔离 hidden acceptance；不把预算中止直接记为模型能力失败。

| task | 可观察行为 | 归因 |
|---|---|---|
| `httpx-activity-review` | 第 16 个工具调用写入 756-byte 补丁；隐藏验收通过；之后继续 6 次检查，最终触及预算边界。 | 修复正确，但模型没有在验证成功后及时提交。终态应为 `passed`。 |
| `werkzeug-auth-whitespace-3129` | 首轮第 7 个工具调用写入 616-byte 补丁，随后继续约 16 次源码和测试阅读；隐藏验收未通过。补跑也写入 357-byte 补丁，但未通过。 | 已开始编辑，但验证和收敛失败；需要检查补丁是否覆盖完整行为。预算耗尽使本次不能区分“补丁错误”和“未完成验证”的权重。 |
| `pydantic-identity-review` | 两轮均约 22-23 次请求、24-25 次工具调用，集中读取 `tests/test_root_model.py`、`pydantic/main.py` 与 `pydantic/root_model.py`，没有补丁。 | 定位阶段停滞，未形成候选修复。 |
| `httpx-identity-review` | 两轮均约 22 次请求，反复读取 `_urls.py`、URL 测试目录与编码相关测试，没有补丁。 | 定位阶段停滞，测试文件和实现位置搜索未收敛。 |

## 协议级原因

1. provider 的 `total_tokens` 每轮包含累积变长的对话上下文。首轮 request payload 从约 1k 字符增长到约 16-18k 字符，虽然旧工具输出被截断，历史工具调用和助手消息仍持续增加。
2. 40 轮工具上限没有先触发，四项运行均在约 22-24 次请求时先耗尽 token 预算。因此当前瓶颈是上下文增长，不是 shell 执行时间；各任务耗时约 31-61 秒，远低于 900 秒上限。
3. 运行器没有为模型提供“测试通过后立即结束”的显式提交动作。模型完成局部验证后仍倾向继续探索，正确补丁也会被预算状态拖到结束。
4. `httpx-identity-review` 一次补跑的 provider usage 为 65,088，高于 64k。这是下一次请求计入完整 prompt 后的越界，说明固定安全余量不能严格限制该服务的逐轮总 token 计量。

## Held-out 未运行的原因

Click/Jinja 保持 `held_out_provisional`，因为 v1-v4 的预算、上下文压缩和终态规则仍在校准。将协议变化与模型效果混入 held-out 会污染比较；并且策展阶段已接触过这两条任务的修复材料，不能宣称严格干净的 held-out。应在 development 协议冻结并重新确认隔离性后才决定是否运行。

## 后续改进方向

- 将工具调用限为 12-16 次，并在每次工具输出后压缩为结构化摘要；不要把完整历史工具调用持续回传。
- 给模型增加显式 `submit` 工具或“测试通过即结束”的终止指令，提交后立即运行 hidden acceptance。
- 预算改为每轮独立请求 token 上限加总，或使用服务端可预估 prompt-token 字段；当前 `total_tokens` 事后计量无法严格防止越界。
- 先在 development 运行一条单任务校准，协议冻结后再评测整组，held-out 保持不动。
