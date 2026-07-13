# Capability 评测快照（2026-07-13）

**数据集：** `capability_dataset.json`  
**规则评分：** `capability_scorer`（非 LLM Judge）  
**原始报告：** 本地运行产物（未强制入库）；摘要如下。

| 维度 | 通过 | 说明 |
|------|:----:|------|
| accuracy | 4/4 | 最终答案命中 |
| tool_selection | 4/4 | 工具精确率/召回/F1 |
| reasoning | 3/3 | 检查点 + 答案 |
| consistency | 3/3 | 同题多次一致 |
| hallucination | 4/4 | 禁止主张 / grounded |
| **合计** | **18/18** | pass_rate = 100% |

> 说明：该快照验证的是**规则打分器与用例设计**在一次真实 Agent 跑批上的结果；样本量仍小，不代表生产评测基准。

另见功能向人工整理报告：[eval_report_20260713.md](./eval_report_20260713.md)（DeepSeek，**23/26 = 88%**）。
