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

## LangGraph environments

The historical LangGraph experiment uses the 0.2 API and remains in the optional
`react-agent[langgraph]` environment. `llm-eval-engine[sdk]` uses LangGraph 1.x.
Do not install these extras into the same environment. Run them as separate processes and
exchange `evaluation-episode/v1` JSON. The protocol boundary is intentional: evaluation and
trace analysis do not require the Agent SDK that produced an episode.
