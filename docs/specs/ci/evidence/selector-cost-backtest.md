# Selector cost backtest

**Generated:** 2026-11-01
**Mode:** report-only
**Sample:** latest 100 PR entries in `phase0-baseline.json`
**Commands:**

`D:\agent_learning_projects\react-agent\.venv\Scripts\python.exe scripts/ci/label_expected_checks.py --sample-size 100`

`D:\agent_learning_projects\react-agent\.venv\Scripts\python.exe scripts/ci/selector_cost_backtest.py --sample-size 100 --output docs/specs/ci/evidence/selector-cost-backtest-100-labelled.json`

The replay used the fixed PR path sample and the current `pr-check-registry.json`. Historical GitHub Actions runs were used only to estimate wall time for jobs that were actually present; missing runs or incomplete timestamps remain unmeasured.

Results:

- 100 PRs replayed; 61 had no unmapped changed paths;
- 31 mapped PRs had usable historical job durations, while 30 had incomplete or unavailable workflow measurements;
- overall estimated median improvement: **2.70%**;
- the independent expected-check labels had zero missing checks and zero stale sample heads;
- the historical `test`, `test-windows`, and `typecheck` failures outside the selected set are diagnostic only, not selector misses;
- subset gate eligibility: **blocked**.

PR #90 changed documentation and its old run failed checks outside the selected documentation scope. The independent label set classifies it as `pr-ready` plus `docs-eval`, so those historical failures are not required checks for that change class. This still does not authorize a hard gate: the 20% threshold is not met and a live report-only observation window has not completed.

The selector therefore remains report-only. Branch Protection and required checks are unchanged. The independent labels are in [selector-expected-checks-100.json](selector-expected-checks-100.json); replay rows, run IDs, SHA values, selected checks, and duration estimates are in [selector-cost-backtest-100-labelled.json](selector-cost-backtest-100-labelled.json).
