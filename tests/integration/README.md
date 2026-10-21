# Integration Tests

Cross-module integration tests that verify end-to-end workflows and external integrations.

## Structure

- `test_shared_idempotency.py` - Idempotency across runs
- `test_real_llm.py` - Live LLM integration tests (requires API key)
- `test_sibling_paths.py` - Cross-repository integration
- `test_fastapi_skill_api.py` - FastAPI skill API integration

## Test Markers

- `real_llm_smoke` - Minimal live LLM subset for CI
- `real_llm` - Full live LLM test suite

Run with:
```bash
pytest tests/integration/ -v -m real_llm_smoke  # Smoke tests
pytest tests/integration/ -v -m real_llm         # Full suite
```

## Requirements

Live LLM tests require `DEEPSEEK_API_KEY` environment variable or secret.
Tests are automatically skipped when the key is not available.
