"""Opt-in real-model validation for the Security Triage report editor."""
from __future__ import annotations

import os

import pytest

from react_agent.apps.security_triage.llm_report import generate_llm_report
from react_agent.apps.security_triage.workflow import run_triage


def _has_key() -> bool:
    provider = os.environ.get("LLM_PROVIDER", "deepseek").lower()
    if provider == "openai":
        return bool(os.environ.get("OPENAI_API_KEY"))
    if provider == "custom":
        return bool(os.environ.get("LLM_API_KEY"))
    return bool(os.environ.get("DEEPSEEK_API_KEY"))


pytestmark = [pytest.mark.real_llm, pytest.mark.real_llm_smoke, pytest.mark.skipif(not _has_key(), reason="需要配置当前 LLM provider API key")]


def test_real_model_security_report_is_validated_and_bounded():
    case = run_triage(
        {
            "cve_ids": ["CVE-2021-44228"],
            "iocs": ["example.invalid"],
        }
    )["case"]
    os.environ.setdefault("REACT_AGENT_SECURITY_LLM", "1")
    output, metadata = generate_llm_report(case)
    # A model may be rejected for failing the strict contract; fallback metadata
    # must still make the reason observable and never accept unsafe prose.
    assert metadata["prompt_version"] == "security-triage-report/v2"
    assert metadata["evidence_sha256"]
    if output is not None:
        assert metadata["fallback"] is False
        assert "not executed" in output.lower() or "not_executed" in output.lower()
        assert "[NVD-CVE-2021-44228]" in output or "[CISA-KEV]" in output
    else:
        assert metadata["fallback"] is True
        assert metadata["failure"]
