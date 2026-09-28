# v6 离线归因（2026-09-20）

来源：`runs/dev-v6-rest-20260920-105712` 下逐轮 request、model、tool 文件及 patch.diff。未调用模型服务、未重跑任务、未更改评测协议。

## 可核查发现

| 任务 | 首次最终提醒 | 收到提醒后的响应 | 实际结果 |
| --- | --- | --- | --- |
| Pydantic | request-21，累计 49333 tokens | 第 21 至 25 轮均继续 shell | 补丁为空，验收失败 |
| HTTPX identity | request-17，累计 48751 tokens | 第 17 至 20 轮均继续 shell | 第 8 轮已有补丁，最终验收通过 |
| Werkzeug | request-21，累计 50194 tokens | 第 21 至 23 轮均继续 shell | 第 23 轮补充修复，最终验收通过 |

### Pydantic：复现偏离和重复定位

tool-07、10、17 至 19、23 至 25 使用 `MyInt: TypeAlias = int`，然后分别定义 `class A(RootModel[MyInt])`、`class B(RootModel[int])`。这是两个不同子类，而不是直接比较命名类型别名与底层类型的泛型实例。两个 annotation 都为 int，只能说明该普通别名示例等价，不能推出任务中的命名别名语义。模型反复确认相同 annotation、重读 __eq__，未编辑代码。不能据此声称真正问题所需元数据已不可恢复。

输入 problem.md 只有抽象的 named type alias 描述，缺少公开可见的最小复现示例。这是任务表述可改进之处；若补充，应从公开 issue 提取并注明来源，不能把 hidden acceptance 实现泄露给模型。

### HTTPX：补丁已完成，但测试环境阻断收敛

第 8 轮修改 PATH_SAFE 后输出已显示管道字符被编码、已有转义和其他组件保留。第 9 至 12、18 轮 pytest 因 trio 警告过滤器导入问题受阻，第 19 轮又暴露缺失 trustme。测试命令管道接 tail，使这些失败的 shell exit_code 仍为 0。第 20 轮尝试 git diff，但镜像无 git，exit_code 127，并非成功生成 diff。

因此此前“不是依赖或运行环境问题”的概括不准确：隐藏验收可运行，但上游测试环境不完整，确实造成额外尝试。两种环境门槛必须分别记录。

### Werkzeug：后续探索发现真实缺口

第 6 轮修复直接构造的无参数 challenge，第 7、8 轮测试受缺失 ephemeral_port_reserve 阻断。第 9、10 轮使用 --noconftest 后输出分别为 4 passed 和 92 passed，这不等于完整上游测试通过。

第 22 轮发现 `WWWAuthenticate.from_header('Basic').to_header()` 仍输出尾随空格，第 23 轮补充处理空 token。最终补丁才通过外部验收。因此不能在第 10 轮测试输出通过时推断任务已完成，也不能把所有后续探索归为浪费。

## 提交和上下文机制

上述请求均包含 Finish now 提醒，模型仍选择 shell；工具未被禁用，tool_choice 未指定。这证明自然语言提醒不是硬停止机制，但无法仅据此判断模型内部为何忽略提醒。

compact_messages 只保留最近四组交互，旧内容是最多八条 stdout 或 stderr 尾部 180 字符拼接，不保留对应命令、退出码或持久的修改记录。Werkzeug model-22 将第 6 轮自己的修复描述成已有行为；这与上下文遗失相符，但不能证明单一因果。压缩还会优先选择非空 stdout，从而遗漏 stderr。

## 最小后续顺序

1. 修正环境契约：明确无 git、可用源码导入方式和上游测试依赖缺口；独立验收就绪不能替代上游测试环境就绪。
2. 保留真实测试退出码与完整日志，禁止把管道末端的成功当 pytest 成功；压缩展示与原始证据分开。
3. 将历史摘要改为带命令、退出码和修改记录的结构化摘要，测试跨窗口后仍保留关键事实。
4. 定义独立的最终收尾阶段；若控制器禁止工具或强制收集补丁，记为 controller stop，不能冒充主动 submit。应先做控制流测试，再冻结新协议。
5. 按公开来源澄清 Pydantic 任务复现，并版本化输入。新输入成绩不能直接归因于预算策略改进。

本轮保留 v6 原始结果：development 隐藏验收 3/4，主动提交 1/4，预算合规 4/4。未启动新付费运行，held-out 保持不动。
