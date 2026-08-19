# Portability

## Runtime data

Mutable data is stored outside the installed package. Override the common root with
`REACT_AGENT_DATA_DIR`, or set a dedicated location:

| Artifact | Override |
|---|---|
| Memory | `REACT_AGENT_MEMORY_FILE` |
| RAG index | `REACT_AGENT_RAG_INDEX` |
| Trajectories | `REACT_AGENT_TRAJECTORY_DIR` |
| Evaluation reports | `REACT_AGENT_REPORT_DIR` |
| Docs troubleshoot index | `REACT_AGENT_DOCS_INDEX_DIR` |

Windows defaults to `%LOCALAPPDATA%\react-agent`. Linux follows
`$XDG_DATA_HOME/react-agent`, then `~/.local/share/react-agent`.
Package-local `memory.json` and `rag_index.json` are copied once when the portable target
does not exist. The source file is retained.

Retention and cleanup rules are defined in
[`ARTIFACT_RETENTION.md`](ARTIFACT_RETENTION.md). Runtime trajectories and caches are not
release evidence.

## LangGraph environments

The LangGraph experiment is pinned to the verified 1.2.x API in the optional
`react-agent[langgraph]` environment. `llm-eval-engine[sdk]` also uses LangGraph 1.x.

### 2026-08 verification boundary

The local `llm-eval-engine/.venv` was used to run the framework checks:

```text
langgraph       1.2.11
langchain-core  1.5.4
langchain-openai not installed
```

With this environment, the following evidence is reproducible:

- `pytest -q tests/test_langgraph_harness_contract.py`: 2 passed;
- `python experiments/langgraph/demo_checkpoint_hitl.py`: checkpoint continuation and HITL deny/approve both passed;
- LangGraph recorder output passes the shared Harness Format B validator.

The repository now also contains opt-in live checks:

- `tests/test_langgraph_deepseek_live.py` checks a real provider call;
- `tests/test_mysql_persistence_live.py` checks task and checkpoint recovery after
  recreating the store.

Both are skipped unless `langchain-openai`/`pymysql` and a reachable provider/MySQL
instance are present. In the current environment they were skipped because both
optional packages are absent; no live result is claimed.

This version now matches the tested 1.2.x/1.5.x range in `pyproject.toml`. The full LLM
graph path remains unverified here because `langchain-openai` is absent and no external
API call was made. Before publishing a release, install the declared extra in a clean
environment and run the same contract plus demo commands; then separately test the
provider adapter with a configured key.

MySQL persistence is likewise opt-in. `MySQLCheckpointSaver` and `MySQLTaskStore` create
their tables automatically, but a real database connection, restart recovery, backup,
connection pooling, migration and permission-boundary tests are still required before
calling this production-ready.
Do not install these extras into the same environment. Run them as separate processes and
exchange `evaluation-episode/v1` JSON. The protocol boundary is intentional: evaluation and
trace analysis do not require the Agent SDK that produced an episode.
