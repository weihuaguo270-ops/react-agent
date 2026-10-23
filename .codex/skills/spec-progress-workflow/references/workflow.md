# Workflow contract

`docs/specs/registry.yaml` is JSON-compatible YAML so the workflow can run with
the Python standard library. Each direction declares `goal`, `progress_source`,
`source_spec`, `specs`, and gate configuration.

Multiple detailed Specs under one business direction share the same progress
file. A new detailed Expense Spec updates `expense.specs` and the goal's
reading links, while the direction's registry-declared progress source remains
unchanged unless the stage or acceptance contract changed.

`status` reads only the registry entry, selected progress file, and the report
named by `last_gate`. `gate` obtains the exact command from the selected stage,
runs the direction consistency analyzer before executing it, and reads the
progress source again. Direct stage-gate commands run the same preflight.
`register` is idempotent and never
invents acceptance items or marks a stage complete. `sync` repairs missing goal
links from the registry and then validates without touching progress files.
`validate` catches missing files, broken links, duplicate progress sources,
progress/source mismatches, missing stages or gate commands, and Specs that are
not registered. `watch` is a polling view, not a second state store.
