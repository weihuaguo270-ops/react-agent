# Phase 1 R9 runtime probe contract

This artifact defines the evidence-only runtime probe for fork pull requests.
It is not an R9 acceptance result.

The reusable workflow is pinned to a commit and executes trusted probe code
from the pull request base SHA. It reads the candidate head only for the
stage gate and runs only when the pull request head repository is a fork. The
probe records `base_sha`, `head_sha`, repository identities, and the declared
read-only permission contract. It never receives, prints, or uploads secrets.
The caller pin in `.github/workflows/test.yml` and the workflow's declared
`TRUSTED_WORKFLOW_REF` must identify the same immutable commit; the static R9
audit blocks pin drift before runtime evidence can be accepted.

The probe reports `passed` only when it observes an actual external fork pull
request with both SHAs present. A same-repository pull request reports
`blocked`, and no run is allowed to upgrade R9 without an external fork run.
The `secret_observation` field remains `not_observed`; proving that a secret is
unavailable to fork code requires the trusted pull-request event boundary and
the resulting remote artifact, not a local simulation.

Evidence sources:

- `.github/workflows/r9-runtime-probe.yml`
- `.github/workflows/test.yml` pinned reusable-workflow call
- `scripts/ci/r9_runtime_probe.py`
- `tests/test_r9_runtime_probe.py`
- `docs/specs/ci/evidence/phase1-r9-acceptance.json`

The Phase 1 R9 acceptance remains `blocked` until an artifact from a real fork
pull request is attached at the current head SHA and the stage gate consumes
it. A skipped or blocked result must not be interpreted as a pass.
