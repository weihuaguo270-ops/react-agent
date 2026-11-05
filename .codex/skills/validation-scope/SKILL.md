---
name: validation-scope
description: Choose the smallest relevant validation for a code change and justify only material additions to tests, gates, or validation scope.
metadata:
  short-description: Keep validation focused
---

# Validation Scope

Use this skill when a task adds tests or gates, changes validation workflows, or
materially expands the checks run for a change. Do not require it for routine
focused implementation work that does not expand validation.

## Workflow

1. Identify the changed behavior and its concrete failure risks from the diff,
   relevant contract, and existing tests.
2. Find the current checks that already cover those risks. Prefer extending an
   existing test or command over adding a parallel one.
3. Select the smallest useful validation: focused tests for a local change,
   related integration or contract checks for cross-module behavior, and the
   declared stage gate only when the task claims that stage is complete.
4. If changed paths or risk mapping are unclear, follow the repository's CI
   fallback policy; do not invent an additional broad suite.
5. Add a test or gate only when it covers a concrete risk not already checked.
   Keep scope, fixtures, setup, and runtime proportional to that risk.
6. When validation expands materially, briefly record the distinct risk, its
   trigger, why existing checks do not cover it, and the selected command.

## Review

- Check for duplicate assertions, repeated execution of the same suite, and
  gates that run for changes that cannot affect their contract.
- Preserve checks for distinct failure modes, security boundaries, platform
  behavior, and declared stage acceptance.
- Do not use a test-count target. A test is justified by risk coverage, not by
  its existence or size.
- Do not treat docs evaluation, Harness/Evaluation, or stage acceptance as
  interchangeable with ordinary focused CI; follow each system's own trigger
  and contract.
- A reviewer requests an explanation only for a material expansion, then
  verifies whether existing checks already cover the stated risk.
