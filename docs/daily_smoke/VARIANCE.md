# Daily smoke variance（跨日）

自动由 `examples/eval/run_daily_smoke.py` + GitHub Actions `daily-smoke` 追加。
默认 **offline / mock**（不耗 API）；带 Key 时可选 `--with-agent`。

| date (UTC) | git | exec offline | exec ok | reliability harness | reliability mock | agent smoke | overall |
|------------|-----|-------------:|:-------:|:-------------------:|:----------------:|:-----------:|:-------:|
| 2026-07-17 | `ff06d08` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-07-17 | `556c9da` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-07-18 | `71fd005` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-07-19 | `b5ee1b0` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-07-20 | `a84c364` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-07-21 | `7e683d0` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-07-22 | `dca47e6` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-07-23 | `011bbc2` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-07-24 | `ed74834` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-07-25 | `ad20b66` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-07-26 | `81f5f09` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-07-29 | `2b7303f` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-07-30 | `56a0c43` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-07-31 | `82fd195` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-08-01 | `b26567e` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-08-02 | `26023fa` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-08-03 | `6d3641c` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-08-04 | `89bfd7c` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-08-05 | `66c9f55` | 12/12 | PASS | PASS | PASS | skip | PASS |

## 怎么读

- 看的是**跨日是否稳定**，不是再刷一次公开大快照。
- `agent smoke` 默认 skip；只有 workflow / 本地显式开 `--with-agent` 才跑。
- 复现：`python examples/eval/run_daily_smoke.py`
