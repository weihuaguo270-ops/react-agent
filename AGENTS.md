# Repository Agent Instructions

These instructions apply to the whole repository. Follow them before creating a
commit, updating a pull request, or merging a pull request.

## Preserve the worktree

- Run `git status --short --branch` before editing or committing.
- Treat existing dirty files as user-owned work. Do not reset, checkout, clean,
  stash, stage, or delete unrelated changes.
- Review `git diff` and `git diff --cached` separately. Stage only files that
  belong to the current task.
- Run `git diff --check` before committing.

## Documentation and corpus baseline

- `docs/` is also the `docs_troubleshoot` evaluation corpus. When a change
  modifies `docs/`, run the git-docs evaluation and review its affected cases.
- After the assertions remain valid, refresh and include the corpus baseline in
  the same change:

  ```bash
  python scripts/eval/docs/run_git_docs_eval.py --refresh-baseline
  ```

- Before a PR is considered ready, the baseline must be clean:

  ```bash
  python scripts/ci/check_pr_ready.py
  ```

## Validation

- Use the smallest relevant focused tests first, then run the repository CI
  equivalent for changes that cross module or workflow boundaries.
- For workflow changes, check the event, environment variables, permissions,
  required checks, and the difference between offline/mock and production
  behavior.
- Keep offline fixtures, historical evaluation results, and production claims
  explicitly separate in the PR description.
- Never commit `.env`, API keys, `mcp_servers.json`, `llm_config.json`, local
  trajectories, or generated secrets.

## Pull request lifecycle

- The PR base is `main`; inspect the current remote `main` before updating a
  long-lived branch.
- A PR must not be merged while GitHub reports `CONFLICTING` or `DIRTY`.
- Required checks must correspond to the current PR head SHA. Do not rely on a
  passing run from an older commit.
- This repository uses protected linear history. Use squash merge after all
  required checks pass; do not push directly to `main` or create a merge commit.
- After merging, verify the resulting `main` SHA, the merged PR state, and the
  first relevant CI run on the new main revision.

## Required pre-PR command

Run the read-only audit from the repository root:

```bash
python scripts/ci/check_pr_ready.py
```

For a PR that is about to be merged, also run:

```bash
python scripts/ci/check_pr_ready.py --pr <number> --repo <owner/name>
```

The audit reports blockers and evidence. It does not perform remote writes or
silently repair conflicts. Resolve blockers explicitly, then rerun it.
