# Progress source invariants

Each progress source uses `spec-progress/v1`, declares `spec_id` and
`source_spec`, and contains stages with `not_started`, `in_progress`, or
`complete` status, an exact `gate_command`, acceptance items, and gate evidence.

`complete` requires a successful gate, complete acceptance items, and existing
evidence. `unknown`, `not_run`, `review`, and `hold` are not successful states.
Routine status reads only the requested direction's progress source and recent
gate report; it does not open every detailed Spec or scan the repository.
