# Harness Trajectory Schema

Shared **Format B** JSON for Agent run recordings.

## Canonical source of truth

**[trace-debugger/schemas/agent_trajectory.schema.json](https://github.com/weihuaguo270-ops/trace-debugger/blob/main/schemas/agent_trajectory.schema.json)**

This repo keeps a **compatible subset** as `harness_trajectory.schema.json` for react-agent Harness validation. New fields (multi-path, failure tags) are defined in the trace-debugger schema.

## Roles

| Repo | Role |
|------|------|
| [trace-debugger](https://github.com/weihuaguo270-ops/trace-debugger) | **Schema owner** · analyze · record · stats |
| [react-agent](https://github.com/weihuaguo270-ops/react-agent) | Reference runtime · produce trajectories · StepWatcher bridge |
| [llm-eval-engine](https://github.com/weihuaguo270-ops/llm-eval-engine) | Process reward / eval consumer |

## Interop rules

See [trace-debugger/schemas/README.md](https://github.com/weihuaguo270-ops/trace-debugger/blob/main/schemas/README.md).

1. `step` is **1-based**
2. Prefer `action.arguments` as JSON string
3. Required: `session_id`, `query`, `steps`, `final_answer`
4. Optional Task Episode: `task_episode_id`, `acceptance_criteria[]` — see [HARNESS_HEALTH.md](../docs/HARNESS_HEALTH.md)

Local alias file: [`harness_trajectory.schema.json`](harness_trajectory.schema.json)

## Software task contract

[`software_task.schema.json`](software_task.schema.json) defines the frozen
software-engineering task input used by delivery and evaluation. It requires an
immutable `base_commit`, an explicit test command, acceptance criteria, and
allowed paths. The runtime representation is
`react_agent.eval.software_task.SoftwareTask`; its canonical JSON hash binds
later approvals and baseline/candidate comparisons to the exact task.

`react_agent.eval.software_task_runner.SoftwareTaskRunner` consumes this
contract. It checks the declared test command against an allowlist and runs it
in a disposable Docker or Podman container with no network, a read-only root,
non-root UID, resource limits, and one writable workspace mount.

Demo: `python examples/eval/harness_closed_loop.py`
