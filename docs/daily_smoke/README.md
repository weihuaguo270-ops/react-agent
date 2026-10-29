# Daily smoke log

跨日 variance 原始行（JSONL）与汇总表。定时 GitHub Actions 将它们作为 evidence artifact 保存，不再自动提交仓库、创建 PR 或合并。

| 文件 | 说明 |
|------|------|
| [`VARIANCE.md`](./VARIANCE.md) | 跨日对照表（自动生成） |
| [`log.jsonl`](./log.jsonl) | 每日一行原始结果 |

## 怎么跑

```bash
# 本地（与 CI 相同，不耗 API）
python scripts/eval/smoke/run_daily_smoke.py

# 可选：easy agent 子集（需 Key）
python scripts/eval/smoke/run_daily_smoke.py --with-agent
```

## 定时

GitHub Actions：`.github/workflows/daily-smoke.yml`

- 每天 **UTC 01:00**（约北京时间 **09:00**）
- 也可在 Actions → **Daily smoke** → Run workflow 手动触发
- 结果位于对应 run 的 `daily-smoke-<run_id>` artifact；本地运行会更新当前工作树中的两份文件。
