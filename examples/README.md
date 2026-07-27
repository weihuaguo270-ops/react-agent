# Examples

| 目录 | 用途 |
|------|------|
| [`demos/`](demos/) | 功能演示（Workflow / 排障 / RAG / MCP / Context…） |
| [`eval/`](eval/) | 回归、公开基准、快照发布、daily smoke |
| [`fixtures/`](fixtures/) | 评测夹具（如 Format B 轨迹样例） |

仓库地图：[`docs/STRUCTURE.md`](../docs/STRUCTURE.md)。

## 常用

```bash
# 主场景
python examples/demos/demo_workflow.py
python examples/eval/run_docs_troubleshoot_eval.py

# 公开评测
python examples/eval/run_public_benchmark.py --modes offline
python examples/eval/run_public_rag_benchmark.py
```
