# CI Phase 0 独立复审

## Review identity

- Review target: `main@16d03460fab16914a2752698aeb0053e32f5a3a0`
- Review tree: `d6dd309f111677fe055fa2a98df78c7ba31d0431`
- Clean review checkout: `d68974ccc26e70c2964356cf87faad7b2b0e9e64`
- CI Spec: `docs/specs/ci/spec.md` v1.5
- Acceptance source: `docs/specs/ci/progress.yaml`
- Review mode: read-only, clean checkout, independent of the baseline collection worktree

## Reviewed evidence and commands

Reviewed the CI Spec, redesign plan, registry v2 schema and registry, CI progress source, the frozen snapshot `main-8805e5e9-20261030`, the current observation, the Phase 0 gate implementation and focused tests, the R9 static snapshot, and the Harness/Evaluation boundary definitions.

Commands used in the clean review context included:

```text
git rev-parse HEAD
git rev-parse HEAD^{tree}
python -m pytest -q -p no:cacheprovider tests/test_ci_registry_v2.py tests/test_ci_stage_gate.py tests/test_refresh_phase0_baseline.py
python scripts/ci/ci_stage_gate.py --stage "Phase 0"
python .codex/skills/spec-progress-workflow/scripts/spec_workflow.py validate
python scripts/ci/check_pr_ready.py
```

## Findings

1. The frozen snapshot has a stable identity, provenance, sample boundaries, and verified artifact hashes. The historical snapshot remains separate from the current observation.
2. The current observation is bound to the observed `main` SHA and retains the required PR, workflow-run, Branch Protection, required-check, failure-job, and reproduction-command fields. It is refreshable evidence and does not replace the frozen snapshot.
3. Historical failures were not silently overwritten. The older snapshot and historical failure review remain readable under their original paths.
4. CI, Harness, and Evaluation responsibilities are separated. CI consumes deterministic exit codes and structured summaries; Harness/Evaluation remains evidence-oriented and retains its own fixture, runner, scoring, replay, and trajectory semantics.
5. The Phase 0 scope does not require the Phase 1 Registry semantic validator, selector backtest, R9 isolated remote execution, Phase 2 shadow window, or later Branch Protection migration. Those are later-stage prerequisites and are not counted as Phase 0 completion.
6. The current-observation manifest previously listed `manifest.json` in its own artifact hash set, which cannot be self-consistent. The collector now excludes the manifest itself from `artifacts`; the manifest remains the index for the external evidence files.

## Conclusion: Partial

Phase 0 is **Partial**. Evidence lifecycle separation, frozen snapshot integrity, current observation capture, and the CI/Harness/Evaluation boundary are sufficiently demonstrated. The manifest-integrity repair has been applied and revalidated, and this review is recorded in the progress source. The Phase 0 gate remains blocked because the independent review conclusion is `Partial`; the maintainer must decide whether the remaining evidence and later-stage prerequisites justify a phase transition.

## Phase 1 prerequisites

- Re-run the current-observation collector with the repaired manifest writer and verify every external artifact hash.
- Re-run the Phase 0 gate and retain its report and SHA256 in `progress.yaml`.
- Keep the frozen snapshot and historical failure records immutable.
- Before Phase 1 can complete, produce a fixed selector sample with deterministic replay, honest unmapped and unmeasured metrics, and isolated R9 workflow permission/Secret evidence.
- Do not change Branch Protection or make AI Review/Harness/Evaluation evidence required checks as part of this review.
