# 公开 Agent benchmark 子集（public_benchmark_snapshot_offline）

- **report_id:** `public_bench_20260717_015153`
- **bundle:** `public_agent_benchmark_subset_v1` v`1`
- **dataset:** `public_benchmark_subset.json`
- **modes:** `offline`
- **通过率:** **20/20（100.0%）**
- **Wilson 95% CI:** [83.9, 100.0]%
- **说明:** 公开子集 n=20（GSM8K×10 + HotpotQA×10）；offline 只验证匹配器；agent 数字绑定模型/日期，勿当全量榜

## 按 benchmark

| benchmark | passed | total | rate |
|-----------|--------|-------|------|
| `gsm8k` | 10 | 10 | 100.0% |
| `hotpotqa` | 10 | 10 | 100.0% |

## 按 mode

| mode | passed | total | rate |
|------|--------|-------|------|
| `offline` | 20 | 20 | 100.0% |

## 明细

- [PASS] `gsm8k_test_0000` (gsm8k/offline): pred=18 gold=18
- [PASS] `gsm8k_test_0001` (gsm8k/offline): pred=3 gold=3
- [PASS] `gsm8k_test_0002` (gsm8k/offline): pred=70000 gold=70000
- [PASS] `gsm8k_test_0003` (gsm8k/offline): pred=540 gold=540
- [PASS] `gsm8k_test_0004` (gsm8k/offline): pred=20 gold=20
- [PASS] `gsm8k_test_0005` (gsm8k/offline): pred=64 gold=64
- [PASS] `gsm8k_test_0006` (gsm8k/offline): pred=260 gold=260
- [PASS] `gsm8k_test_0007` (gsm8k/offline): pred=160 gold=160
- [PASS] `gsm8k_test_0008` (gsm8k/offline): pred=45 gold=45
- [PASS] `gsm8k_test_0009` (gsm8k/offline): pred=460 gold=460
- [PASS] `hotpot_val_0000` (hotpotqa/offline): contains
- [PASS] `hotpot_val_0001` (hotpotqa/offline): contains
- [PASS] `hotpot_val_0002` (hotpotqa/offline): contains
- [PASS] `hotpot_val_0003` (hotpotqa/offline): contains
- [PASS] `hotpot_val_0004` (hotpotqa/offline): contains
- [PASS] `hotpot_val_0005` (hotpotqa/offline): contains
- [PASS] `hotpot_val_0006` (hotpotqa/offline): contains
- [PASS] `hotpot_val_0007` (hotpotqa/offline): contains
- [PASS] `hotpot_val_0008` (hotpotqa/offline): contains
- [PASS] `hotpot_val_0009` (hotpotqa/offline): contains

## License

GSM8K: MIT (OpenAI). HotpotQA: CC BY-SA 4.0. Redistributed subset for evaluation only.

---

- git: `e9b1bb4`
- archived_json: `docs/snapshots/public_benchmark_snapshot_offline.json`
- reproduce: `python examples/run_public_benchmark.py --modes offline --publish`
