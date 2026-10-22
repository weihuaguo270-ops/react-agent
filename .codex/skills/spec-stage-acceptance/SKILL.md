---
name: spec-stage-acceptance
description: Run Spec-defined project phase gates and report progress from the repository's single progress file, updating evidence without rescanning the whole project.
metadata:
  short-description: Spec phase gates and progress tracking
---

# Spec Stage Acceptance

Use this skill when a user asks to check project progress, accept a phase, verify
an implementation stage, or continue work governed by a Spec with staged
acceptance criteria.

## Source of truth

1. Locate the repository's declared progress file, preferring `progress.yaml`
   or the path named by the Spec. Read that file first and use it as the only
   source for routine progress questions.
2. Do not rescan the repository to answer a progress question. Report the
   stage status, pending acceptance IDs, latest gate command, report path and
   report SHA256 from the progress file.
3. Read the governing Spec only when starting a new phase, interpreting an
   acceptance item, or checking whether the progress file's schema is stale.

## Phase gate workflow

1. Identify the requested direction and phase from the registry and progress
   file. Run `spec_workflow.py analyze --direction <id>` before changing phase
   work; resolve every error before running a gate.
2. Run the exact `gate_command` from the progress file from the repository
   root. The gate script repeats the consistency preflight so direct invocations
   cannot bypass it. A phase is complete only
   when the command exits 0, all listed acceptance items are `complete`, and
   every required artifact path and assertion passes.
3. Treat missing evidence, skipped tests, environment blockers, and unknown
   results as incomplete. Never turn them into a pass by inference.
4. Use the gate's generated report as the concise evidence record. Preserve its
   path, command, commit, result, and SHA256 in the progress file.
5. When work changes code, tests, configuration, Spec text, or evidence,
   update the relevant acceptance item and artifact path in the progress file
   before reporting the step complete. Run the phase gate afterward.

## Stage transitions

- Ask for human confirmation only when moving from one phase to the next.
- Within a phase, continue using the automated gate and do not repeatedly ask
  for confirmation.
- Do not mark a later phase complete because an earlier phase's artifacts pass.
- Keep historical, fixture, held-out, production, and environment-limited
  evidence in their declared categories.

## Artifacts

Every material phase action must leave a short JSON/JSONL report or log under
the repository's declared artifact directory. The progress file must point to
that artifact. Do not commit secrets, local configuration, credentials, or
untracked raw trajectories unless the repository policy explicitly requires it.

## Repository integration

If the repository provides a stage-gate script, use it instead of recreating a
test command. For this repository the standard command is:

```powershell
python scripts/ci/harness_stage_gate.py --stage <P0|P1|P2|P3|P4|P5>
```

The command writes `artifacts/harness/stage-gates/<stage>-latest.json` and
updates `progress.yaml`. Read [references/progress-contract.md](references/progress-contract.md)
when adding a new project integration or repairing the progress schema.
