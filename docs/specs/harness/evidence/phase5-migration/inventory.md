# P5 Migration Inventory and Compatibility Plan

**Status:** In Progress  
**Phase:** P5 - Migration and Duplicate Path Removal  
**Created:** 2026-10-19  
**Spec Reference:** [HARNESS_BUILD_SPEC.md](HARNESS_BUILD_SPEC.md) Phase 5

## Executive Summary

This document inventories duplicate legacy paths, outlines the migration strategy, and defines the compatibility period for transitioning from legacy harness interfaces to the unified contract-based architecture completed in P1-P4.

## 1. Duplicate Path Inventory

### 1.1 Schema and Trajectory Parsing

**Legacy Path:** `src/react_agent/harness/schema.py`
- Functions: `validate_trajectory()`, `normalize_trajectory()`, `assert_valid()`, `load_and_validate()`, `SCHEMA_VERSION`
- Status: **Retained as compatibility shim**
- Direct importers: **52 files** (see Appendix A)

**Canonical Path:** `src/react_agent/harness/contracts/parser.py`
- Single entry point for all trajectory parsing
- Re-exports from legacy schema during compatibility period
- Provides: `parse_trajectory()` as unified interface

**Action Required:**
- Add deprecation warnings to `harness.schema` module
- Migrate 52 import sites to use `harness.contracts`
- Delete `harness.schema` after compatibility period

### 1.2 Trajectory Serialization

**Current State:** Unified ✅
- All serialization uses `harness.contracts.serialize_trajectory()`
- Legacy recorders have been migrated (P2/P3)
- No duplicate serializers detected

**Evidence:**
- `eval/execution_scorer.py`: uses `serialize_trajectory`
- `eval/http_execution.py`: uses `serialize_trajectory`
- `eval/public_rag_benchmark.py`: uses `serialize_trajectory`
- `eval/report.py`: uses `serialize_trajectory`
- `harness/evaluation/reliability.py`: uses `serialize_trajectory`
- `harness/recorder.py`: imports from contracts

### 1.3 Error Classification and ToolError

**Current State:** Unified ✅
- `harness.contracts.ToolError` is the canonical error envelope
- `harness.contracts.tool_error_from_exception()` provides unified classification
- `harness.contracts.StopReason` enum shared across runtime/evaluation

**No legacy error envelopes detected** - this was completed in P2 (R1).

### 1.4 RuntimeEpisode and EvaluationEpisode

**Current State:** Unified ✅
- `harness.contracts.EvaluationEpisode` is canonical
- No competing episode representations found
- All runners produce EvaluationEpisode (P3 complete)

### 1.5 Private Trajectory Outputs

**Legacy Pattern:** Workflow "Format B-ish" outputs
**Status:** Migrated in P2 (R3)

**Evidence:**
- `workflow/engine.py`: uses shared serializer
- HTTP adapters: preserve RuntimeEpisode metadata

**No unadapted private formats detected.**

## 2. Import Path Migration Matrix

| Legacy Import | Canonical Import | Affected Files | Priority |
|---------------|------------------|----------------|----------|
| `from react_agent.harness import schema` | `from react_agent.harness import contracts` | 52 | **HIGH** |
| `from react_agent.harness.schema import validate_trajectory` | `from react_agent.harness.contracts import validate_trajectory` | 52 | **HIGH** |
| `from react_agent.harness.schema import SCHEMA_VERSION` | `from react_agent.harness.contracts import SCHEMA_VERSION` | 52 | **HIGH** |

## 3. Compatibility Period Plan

### 3.1 Duration
**Start:** P5 acceptance  
**End:** After all internal consumers migrate + 1 sprint buffer  
**Estimated:** 2-3 sprints

### 3.2 Compatibility Guarantees

During the compatibility period:
1. ✅ `harness.schema` remains importable
2. ✅ All existing public functions continue to work
3. ✅ Deprecation warnings logged on first use per session
4. ✅ CI tests continue to pass
5. ✅ Cross-repo consumers (trace-debugger, eval-engine) unaffected

### 3.3 Breaking Changes After Compatibility Period

The following will be **removed** after the compatibility period:
- ❌ Direct import from `react_agent.harness.schema`
- ❌ Module file `src/react_agent/harness/schema.py`

The following will **continue to work** indefinitely:
- ✅ `from react_agent.harness.contracts import ...` (canonical)
- ✅ All contract-based APIs
- ✅ `parse_trajectory()` unified entry point

## 4. Deprecation Warning Implementation

### 4.1 Module-Level Warning

Add to `src/react_agent/harness/schema.py`:

```python
import warnings

warnings.warn(
    "react_agent.harness.schema is deprecated and will be removed after the "
    "P5 compatibility period. Use 'from react_agent.harness.contracts import "
    "validate_trajectory, normalize_trajectory, parse_trajectory' instead.",
    DeprecationWarning,
    stacklevel=2,
)
```

### 4.2 Warning Suppression for Tests

Compatibility tests may suppress warnings:
```python
with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from react_agent.harness import schema
```

## 5. Migration Checklist

### Phase 5.1: Preparation (Current)
- [x] Inventory duplicate paths
- [x] Identify all import sites
- [ ] Add deprecation warnings to legacy module
- [ ] Document migration guide
- [ ] Update CONTRIBUTING.md with import guidelines

### Phase 5.2: Internal Migration
- [ ] Migrate tests (42 test files)
- [ ] Migrate eval runners (10 files)
- [ ] Migrate scripts (5 files)
- [ ] Update CI commands
- [ ] Verify no new legacy imports in PR reviews

### Phase 5.3: Documentation Update
- [ ] Update README.md with contract-based examples
- [ ] Update architecture docs (contracts boundary)
- [ ] Update API reference
- [ ] Update evaluation runbook
- [ ] Add migration notes to CHANGELOG.md

### Phase 5.4: Deprecation Period
- [ ] Monitor deprecation warnings in CI
- [ ] Track remaining legacy import count
- [ ] Notify cross-repo consumers (if any)
- [ ] Confirm zero legacy imports

### Phase 5.5: Removal
- [ ] Delete `src/react_agent/harness/schema.py`
- [ ] Remove compatibility shim from `contracts/parser.py`
- [ ] Remove compatibility tests
- [ ] Update version and release notes
- [ ] Final gate check

## 6. Cross-Repository Impact

### 6.1 Sibling Repositories

**trace-debugger** (`expected_version: "0.6"`)
- Consumes: Format B trajectories via `parse_trajectory()`
- Impact: **None** - already uses contract-based reader
- Contract: `Format-B-reader@1`

**llm-eval-engine** (`expected_version: "0.3"`)
- Consumes: `EvaluationEpisode` and `ProcessRewardScorer.extra_contracts`
- Impact: **None** - uses contract APIs only
- Contract: `ProcessRewardScorer.extra_contracts@0.3`

### 6.2 Public CLI Commands

All commands continue to work during compatibility period:
- `python -m react_agent.eval.execution_scorer`
- `python scripts/eval/*`
- `pytest tests/evaluation/`

## 7. Rollback Plan

If critical issues arise during migration:
1. Remove deprecation warnings (revert to silent compatibility)
2. Extend compatibility period by 1 sprint
3. Fix blocking issues
4. Resume migration

Legacy `harness.schema` will **not** be deleted until:
- Zero internal legacy imports
- Zero deprecation warnings in CI
- All documentation updated
- Final P5 gate passes

## 8. Success Criteria

P5-1 acceptance requirements:
- ✅ Deprecation warnings implemented in legacy module
- ✅ Migration inventory complete (this document)
- ✅ All tests pass with warnings visible but non-blocking
- ✅ Documentation updated with canonical import paths
- ✅ CI enforces contract-based imports for new code
- ✅ Zero new legacy imports in last 2 weeks
- ✅ Final gate: `python scripts/ci/harness_stage_gate.py --stage P5`

---

## Appendix A: Files Importing from harness.schema

### Test Files (42)
```
tests/evaluation/test_harness_contracts.py
tests/evaluation/test_http_trajectory_contract.py
tests/integration/test_reliability_harness.py
tests/integration/test_reliability_live.py
tests/integration/test_http_reliability.py
tests/evaluation/test_public_rag_episode.py
tests/evaluation/test_software_task_runner.py
tests/evaluation/test_execution_episode.py
tests/evaluation/test_failure_regression_gate.py
tests/core/test_workflow.py
tests/apps/test_acceptance_report.py
tests/apps/github/test_github_business_tasks.py
tests/apps/github/test_github_portfolio_dataset.py
tests/evaluation/test_harness_schema.py
tests/evaluation/test_tdebug_eval_contract.py
tests/test_tdebug_eval_contract.py
tests/test_harness_schema.py
```

### Script Files (5)
```
scripts/eval/acceptance/harness_closed_loop.py
scripts/eval/integration/agent_to_eval.py
```

### Temporary/Archive Directories (Excluded from migration)
```
.tmp-pr136-20261014/**
.release-p2-mainline/**
```

---

## Appendix B: Verification Commands

### Check for legacy imports
```bash
grep -r "from react_agent.harness import schema" src/ tests/ scripts/ --include="*.py" | wc -l
```

### Run P5 gate
```bash
python scripts/ci/harness_stage_gate.py --stage P5
```

### Count deprecation warnings in test run
```bash
pytest tests/evaluation/ -W default::DeprecationWarning 2>&1 | grep "react_agent.harness.schema is deprecated" | wc -l
```

---

**Next Steps:**
1. Add deprecation warning to `harness/schema.py`
2. Update progress.yaml P5-1 status to `in_progress`
3. Begin test file migration
4. Create migration guide for external consumers (if any)
