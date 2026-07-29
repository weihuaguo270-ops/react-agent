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

Local alias file: [`harness_trajectory.schema.json`](harness_trajectory.schema.json)

Demo: `python examples/eval/harness_closed_loop.py`
