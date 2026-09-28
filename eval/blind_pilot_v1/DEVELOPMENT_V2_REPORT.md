# Development calibration v2

Scope: four development tasks only. No held-out reruns. Original pilot preserved.

Observed hidden pass rate: 0/4. All runs budget_exhausted. Total usage 78228 tokens; summed elapsed 107.35s. Actual cost unknown. No full upstream regression score.

Every request's actual prompt usage was below its conservative byte reservation. Thus no measured budget overrun, but reservation still stopped runs substantially early. Old tool output compaction extended runs without resolving the issue. Model also spent turns fixing Python source import paths for temporary scripts.

Protocol is NOT frozen for held-out. Next implementation needs source-path setup and provider-compatible token counting, or an explicitly revised budget definition. Do not silently replace the total-token cap with a completion-only cap. No further paid reruns until accounting is validated offline against recorded request/usage pairs.
