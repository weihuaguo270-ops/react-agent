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
| 2026-08-06 | `3bcefd4` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-08-07 | `c6ec72c` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-08-08 | `4354129` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-08-09 | `2c9a215` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-08-10 | `7e50042` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-08-11 | `1096b89` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-08-12 | `eaf859d` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-08-13 | `b094ce4` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-08-14 | `f08c436` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-08-16 | `46b2b23` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-08-17 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-08-18 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-08-19 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-08-20 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-08-21 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-08-22 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-08-23 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-08-24 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-08-25 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-08-26 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-08-27 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-08-28 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-08-29 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-08-30 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-08-31 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-09-01 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-09-02 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-09-03 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-09-04 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-09-05 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-09-06 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-09-07 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-09-08 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-09-09 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-09-10 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-09-11 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-09-12 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-09-13 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-09-14 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-09-15 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-09-16 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-09-17 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-09-18 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-09-19 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-09-20 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-09-21 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-09-22 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-09-23 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-09-24 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-09-25 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-09-26 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-09-27 | `41fbae5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-09-28 | `bdb5d42` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-09-29 | `8fcd250` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-09-30 | `6af1bb5` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-10-01 | `ddb4a2d` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-10-01 | `4706856` | 12/12 | PASS | PASS | PASS | skip | PASS |
| 2026-10-02 | `b0b097a` | 12/12 | PASS | PASS | PASS | skip | PASS |

## 怎么读

- 看的是**跨日是否稳定**，不是再刷一次公开大快照。
- `agent smoke` 默认 skip；只有 workflow / 本地显式开 `--with-agent` 才跑。
- 复现：`python examples/eval/run_daily_smoke.py`
