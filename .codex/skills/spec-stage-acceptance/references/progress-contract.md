# Progress Contract

The progress file is a JSON document stored with a `.yaml` suffix so projects
may use it as either YAML or JSON. It contains:

```yaml
schema_version: harness-progress/v1
stages:
  P2:
    status: in_progress
    gate_command: python scripts/ci/harness_stage_gate.py --stage P2
    acceptance:
      - id: R1
        status: in_progress
        evidence: [artifacts/harness/p2-r1-cross-path.json]
    last_gate:
      status: failed
      report: artifacts/harness/stage-gates/p2-latest.json
      report_sha256: "..."
last_gate: ...
```

Required status values are `not_started`, `in_progress`, and `complete`.
`complete` is valid only after the gate exits 0 and all acceptance and evidence
checks pass. A report with `test_exit_code: 0` is insufficient when required
evidence is missing.

For routine status output, read only:

- the requested stage under `stages`;
- its `last_gate` object;
- acceptance items whose status is not `complete`.

Do not enumerate source files, tests, containers, or artifacts to answer that
routine question. Enumeration belongs inside the explicit phase gate command.
