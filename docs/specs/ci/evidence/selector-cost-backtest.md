# Selector cost backtest

**Generated:** 2026-11-01
**Mode:** report-only
**Sample:** latest 100 PR entries in `phase0-baseline.json`
**Command:** `D:\agent_learning_projects\react-agent\.venv\Scripts\python.exe scripts/ci/selector_cost_backtest.py --sample-size 100 --output docs/specs/ci/evidence/selector-cost-backtest-100.json`

The replay used the fixed PR path sample and the current `pr-check-registry.json`. Historical GitHub Actions runs were used only to estimate wall time for jobs that were actually present; missing runs or incomplete timestamps remain unmeasured.

Results:

- 100 PRs replayed; 59 had no unmapped changed paths;
- 47 mapped PRs had usable historical job durations, while 12 had incomplete or unavailable workflow measurements;
- estimated median improvement: **3.92%**;
- 2 historical check names (`test-windows`, `typecheck`) occurred outside the selected set on at least one old run;
- zero missed required checks is **not proven**, because the repository has no independent expected-check labels for the historical sample;
- subset gate eligibility: **blocked**.

The historical failures outside the selected set are diagnostic evidence, not proof that the selector missed a required check. For example, PR #90 changed documentation and its old run failed checks outside the selected documentation scope. The result still requires an explicit expected-check label set and report-only observation before any hard gate can be enabled.

The selector therefore remains report-only. Branch Protection and required checks are unchanged. The structured rows, run IDs, SHA values, selected checks, and duration estimates are in [selector-cost-backtest-100-current.json](selector-cost-backtest-100-current.json); the earlier 20-PR pilot is preserved in [selector-cost-backtest.json](selector-cost-backtest.json).
