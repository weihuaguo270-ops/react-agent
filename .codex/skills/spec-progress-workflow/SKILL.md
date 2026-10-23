---
name: spec-progress-workflow
description: Register repository Specs and query, gate, validate, or watch one authoritative progress source per business direction.
metadata:
  short-description: Spec routing and progress workflow
---

# Spec Progress Workflow

Use this skill when a task changes a repository Spec structure, asks for current
progress, needs a phase gate, adds a detailed Spec, or needs to verify that Spec
routing and progress configuration are consistent.

Read `docs/specs/ORGANIZATION_RULES.md` first. Then read only the requested
direction's entry in `docs/specs/registry.yaml`, its goal file, and the
registry-declared progress source. A direction may contain many detailed Specs,
but it has exactly one progress source. Detailed Specs describe contracts; they
never become a second status authority.

Run the helper from the repository root:

```powershell
python .codex/skills/spec-progress-workflow/scripts/spec_workflow.py <mode> ...
```

Modes:

- `status --direction <id>` reads the current progress source and recent gate
  report on every invocation. Use it for a current or real-time point query.
- `analyze --direction <id>` compares registered Specs, goal routing, progress,
  stage status, acceptance items, gate reports, and evidence paths. Resolve every
  error before executing a stage gate; review findings are historical or
  unverifiable evidence and must not be promoted to a pass.
- `gate --direction <id> --stage <stage>` reads that stage's exact
  `gate_command` from the progress source, runs it, and reports the resulting
  progress and artifact hash. Do not infer completion from tests outside the
  declared gate. The gate command performs the consistency preflight first.
- `register --direction <id> --spec <path>` adds a detailed Spec to an existing
  direction and updates its registry and goal reading route. It does not create
  a progress file or copy status. For a new direction, provide `--new-direction`,
  `--goal`, `--progress-source`, and `--source-spec`; review the generated files
  before using a gate.
- `validate` checks registry, goals, progress sources, detailed Specs, duplicate
  progress sources, and missing gate mappings without scanning unrelated source
  code.
- `sync` repairs missing detailed Spec links in registered goal files, then runs
  the same configuration checks. It never creates or updates a progress source.
- `watch --direction <id>` polls the declared progress source and emits only
  changes; stop it when the live observation is no longer needed.

When a registration would overwrite existing content or cannot determine the
direction, stop with a reviewable error. Preserve existing worktree changes and
run the repository's required documentation and readiness checks after changing
`docs/`.

For implementation work, keep the loop explicit: analyze the contracts and
acceptance mapping, implement one bounded stage slice, run its declared gate,
inspect the generated report, then update progress from the gate evidence. If a
format, schema, or validation failure shows the Spec is incomplete or
contradictory, update the authoritative Spec and affected references before
retrying; do not patch around the contract silently.

Read [references/workflow.md](references/workflow.md) for the mode contract and
[references/progress-contract.md](references/progress-contract.md) for the
single-source invariants. The helper accepts the repository path through
`--root` when invoked outside the checkout.
