# Tests Structure

Modular test organization for react-agent.

## Directory Structure

```
tests/
├── apps/                    # Application-specific tests
│   ├── docs_troubleshoot/   # Document troubleshooting app tests
│   └── github/              # GitHub integration tests
├── core/                    # Core runtime tests
│   ├── test_react_loop.py
│   ├── test_orchestrator.py
│   ├── test_planner.py
│   ├── test_tools.py
│   ├── test_llm.py
│   ├── test_context.py
│   ├── test_memory.py
│   ├── test_cot.py
│   ├── test_workflow.py
│   ├── test_resilience.py
│   ├── test_tool_scope.py
│   └── test_write_sets.py
├── harness/                 # Harness and trajectory tests
│   ├── test_harness_r2.py
│   ├── test_deterministic_replay.py
│   └── test_runtime_observability.py
├── safety/                  # Safety and permissions tests
│   └── test_permissions_gate.py
├── experimental/            # Experimental feature tests
│   ├── test_mcp_mock.py
│   └── test_mcp_stdio_contract.py
├── integration/             # Integration and E2E tests
│   ├── test_shared_idempotency.py
│   ├── test_real_llm.py
│   └── test_sibling_paths.py
├── evaluation/              # Evaluation framework tests
│   ├── test_capability_scorer.py
│   ├── test_eval_runner_episode.py
│   ├── test_failure_regression_*.py
│   ├── test_software_task_*.py
│   └── test_step_watcher_*.py
├── rag/                     # RAG and retrieval tests
│   ├── test_rag_keyword.py
│   └── test_rag_semantic.py
├── security/                # Security tests
│   └── test_permissions_gate.py
├── service/                 # Service layer tests
│   ├── test_async_approvals.py
│   └── test_fastapi_async_approvals.py
└── storage/                 # Storage and persistence tests
    └── test_postgresql_task_store.py
```

## Running Tests

### All tests
```bash
pytest tests/ -v
```

### By category
```bash
pytest tests/core/ -v                    # Core functionality
pytest tests/harness/ -v                 # Harness and trajectories
pytest tests/safety/ -v                  # Safety mechanisms
pytest tests/integration/ -v             # Integration tests
pytest tests/apps/docs_troubleshoot/ -v  # Docs troubleshoot app
```

### By marker
```bash
pytest tests/ -v -m real_llm_smoke       # Live LLM smoke tests
pytest tests/ -v -m real_llm             # Full live LLM tests
```

### Offline tests only (no LLM)
```bash
pytest tests/ -v -m "not real_llm"
```

## Test Guidelines

1. **Unit tests** go in the module-specific directory (core/, harness/, etc.)
2. **Integration tests** that span multiple modules go in `integration/`
3. **Application tests** go in `apps/{app_name}/`
4. **Live LLM tests** should be marked with `@pytest.mark.real_llm` or `@pytest.mark.real_llm_smoke`
5. **Each subdirectory** should have a README.md explaining its scope

## Configuration

- `conftest.py` - Shared fixtures and pytest configuration
- `pyproject.toml` - pytest settings, markers, and temp directory config

## CI

The CI workflow runs:
1. **lint** - Ruff linting (F rules only)
2. **test** - Offline unit tests + cross-repo contract tests
3. **typecheck** - mypy on src/
4. **security** - pip-audit in clean venv
5. **Real LLM gate** - Detects if DEEPSEEK_API_KEY is available
6. **Real LLM (smoke)** - Runs real_llm_smoke tests if key is available
7. **Real LLM (full)** - Manual workflow for full real_llm suite

Required checks for merge: lint, test (3.10/3.11), test-windows (3.10/3.11), typecheck, security, docker-smoke, Real LLM gate.
