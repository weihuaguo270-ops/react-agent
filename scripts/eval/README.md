# Eval entry scripts

Runnable gates and acceptance entrypoints. Library code stays in `src/react_agent/eval/`.

| Subdir | Role |
|--------|------|
| `execution/` | Tool / agent execution suites |
| `reliability/` | Guard / reliability harness and live(mock) |
| `docs/` | Docs-troubleshoot golden / fault / production / git-docs |
| `rag/` | Public RAG benchmark |
| `failure/` | Flywheel, failure-regression, step-watcher, repair evidence |
| `acceptance/` | Portfolio / harness closed-loop / business task acceptance |
| `smoke/` | Daily smoke, deploy smoke, sandbox live check |
| `publish/` | Snapshot publish helpers |
| `integration/` | Cross-repo agent→eval demos |

CI invokes these paths from `.github/workflows/`.
