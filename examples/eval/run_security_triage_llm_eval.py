"""Compare deterministic and real LLM Security Triage report paths.

The script uses the repository's configured OpenAI-compatible provider. It does
not persist prompts, API keys, or model output; only aggregate validation metrics
and bounded failure reasons are emitted.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from react_agent.apps.security_triage.llm_report import generate_llm_report
from react_agent.apps.security_triage.workflow import run_triage
from react_agent.llm import LLM

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _resolve_dataset(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_file():
        return candidate
    rooted = _REPO_ROOT / candidate
    if rooted.is_file():
        return rooted
    raise FileNotFoundError(f"security triage dataset not found: {path}")


def _candidate_spec(spec: str) -> tuple[str, str | None]:
    provider, separator, model = spec.partition(":")
    return provider.strip(), model.strip() if separator and model.strip() else None


def _live_chat(provider: str, model: str | None):
    client = LLM(provider=provider)
    if model:
        client.model = model

    def chat(prompt: str, _: dict[str, Any]) -> dict[str, Any]:
        response = client.chat(
            [
                {"role": "system", "content": "You edit evidence-bound security reports."},
                {"role": "user", "content": prompt},
            ],
            tool_defs=None,
            temperature=0,
            max_tokens=1800,
            max_retries=1,
        )
        return response

    return client, chat


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) * 0.95 + 0.999999) - 1)))
    return round(ordered[index], 3)


def _forbidden_assertion(answer: str, term: str) -> bool:
    """Detect positive safety claims while ignoring evidence-bound negations."""
    normalized = answer.lower()
    if term in {"safe", "unaffected"}:
        pattern = (
            rf"\b(?:is|appears|confirmed|considered|deemed)\s+{re.escape(term)}\b"
            if term == "unaffected"
            else rf"\b(?:is|appears|confirmed|considered|deemed)\s+safe\b|\bsafe\s+to\b"
        )
        for match in re.finditer(pattern, normalized):
            prefix = normalized[max(0, match.start() - 45) : match.start()]
            if re.search(r"\b(?:not|no|without|absence\s+of|does\s+not|doesn't|cannot|can't|never)\b[^.!?]*$", prefix):
                continue
            return True
        return False
    if term == "malicious=true":
        return bool(re.search(r"\bmalicious\s*=\s*true\b", normalized))
    return term in normalized


def _contains_expected(answer: str, term: str) -> bool:
    """Match stable IDs and humanized machine labels (underscore or spaces)."""
    normalized = answer.lower()
    candidates = {term.lower(), term.lower().replace("_", " ")}
    if any(candidate in normalized for candidate in candidates):
        return True
    if "_" in term:
        tokens = [re.escape(token) for token in term.lower().split("_") if token]
        if tokens and re.search(r"\b" + r"\b.{0,40}?\b".join(tokens) + r"\b", normalized):
            return True
    return False


def _case_expectation(case: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    kev_values = [item["listed"] for item in case.get("kev", [])]
    asset_values = [item["matched"] for item in case.get("asset_matches", [])]
    priorities = [item["priority"] for item in case.get("recommendations", [])]
    return {
        "kev_listed": expected["kev_listed"] is None or expected["kev_listed"] in kev_values,
        "asset_matched": expected["asset_matched"] is None or expected["asset_matched"] in asset_values,
        "priority": expected["priority"] in priorities,
        "review_status": case.get("status") == expected.get("review_status", "pending_review"),
        "executed_actions": len(case.get("executed_actions", [])) == expected.get("executed_actions", 0),
    }


def evaluate(dataset_path: str, candidates: list[str], repetitions: int = 2) -> dict[str, Any]:
    if repetitions < 1 or repetitions > 3:
        raise ValueError("repetitions must be between 1 and 3")
    dataset = json.loads(_resolve_dataset(dataset_path).read_text(encoding="utf-8"))
    outputs: list[dict[str, Any]] = []
    for candidate_spec in candidates:
        provider, model = _candidate_spec(candidate_spec)
        client, chat = _live_chat(provider, model)
        valid_count = 0
        fallback_count = 0
        model_fact_consistent = 0
        final_fact_consistent = 0
        model_boundary_preserved = 0
        final_boundary_preserved = 0
        false_safe_assertions = 0
        failures: dict[str, int] = {}
        category_stats: dict[str, dict[str, int]] = {}
        latencies: list[float] = []
        baseline_valid = 0
        for item in dataset:
            category = str(item.get("category") or "uncategorized")
            stats = category_stats.setdefault(
                category,
                {
                    "evaluations": 0,
                    "valid": 0,
                    "fallback": 0,
                    "model_fact_consistent": 0,
                    "final_fact_consistent": 0,
                    "model_boundary_preserved": 0,
                    "final_boundary_preserved": 0,
                    "false_safe_assertions": 0,
                },
            )
            baseline_result = run_triage(item["input"])
            case = baseline_result["case"]
            baseline_valid += 1 if case.get("citations") and case.get("executed_actions") == [] else 0
            expected = item.get("expect") or {}
            expected_terms = [str(term).lower() for term in expected.get("required_terms", [])]
            forbidden_terms = [str(term).lower() for term in expected.get("forbidden_terms", [])]
            for _ in range(repetitions):
                stats["evaluations"] += 1
                started = time.monotonic()
                output, metadata = generate_llm_report(case, llm=client, chat=chat)
                latencies.append(round((time.monotonic() - started) * 1000, 3))
                final_output = output or baseline_result["answer"]
                final_fact_consistent += 1 if all(_contains_expected(final_output, term) for term in expected_terms) else 0
                final_boundary_preserved += 1 if "not_executed" in final_output or "not executed" in final_output.lower() else 0
                stats["final_fact_consistent"] += int(all(_contains_expected(final_output, term) for term in expected_terms))
                stats["final_boundary_preserved"] += int("not_executed" in final_output or "not executed" in final_output.lower())
                if output is not None:
                    valid_count += 1
                    stats["valid"] += 1
                    model_fact_consistent += 1 if all(_contains_expected(output, term) for term in expected_terms) else 0
                    model_boundary_preserved += 1 if "not_executed" in output or "not executed" in output.lower() else 0
                    stats["model_fact_consistent"] += int(all(_contains_expected(output, term) for term in expected_terms))
                    stats["model_boundary_preserved"] += int("not_executed" in output or "not executed" in output.lower())
                    safe_assertions = sum(
                        1 for term in forbidden_terms if _forbidden_assertion(output, term)
                    )
                    false_safe_assertions += safe_assertions
                    stats["false_safe_assertions"] += safe_assertions
                else:
                    fallback_count += 1
                    stats["fallback"] += 1
                    failure = str(metadata.get("failure") or "unknown")
                    failures[failure] = failures.get(failure, 0) + 1
        total = len(dataset) * repetitions
        outputs.append(
            {
                "candidate": candidate_spec,
                "provider": provider,
                "model": model or client.model,
                "cases": len(dataset),
                "repetitions": repetitions,
                "evaluations": total,
                "baseline_valid_reports": baseline_valid,
                "llm_valid_reports": valid_count,
                "llm_valid_rate": valid_count / total if total else 1.0,
                "citation_bound_rate": valid_count / total if total else 1.0,
                "model_fact_consistency_rate": model_fact_consistent / valid_count if valid_count else 0.0,
                "final_fact_consistency_rate": final_fact_consistent / total if total else 1.0,
                "model_boundary_preservation_rate": model_boundary_preserved / valid_count if valid_count else 0.0,
                "final_boundary_preservation_rate": final_boundary_preserved / total if total else 1.0,
                "fallback_rate": fallback_count / total if total else 0.0,
                "false_safe_assertions": false_safe_assertions,
                "mean_latency_ms": round(sum(latencies) / len(latencies), 3) if latencies else 0.0,
                "p95_latency_ms": _p95(latencies),
                "failures": failures,
                "by_category": {
                    category: {
                        "evaluations": stats["evaluations"],
                        "valid_rate": stats["valid"] / stats["evaluations"] if stats["evaluations"] else 1.0,
                        "fallback_rate": stats["fallback"] / stats["evaluations"] if stats["evaluations"] else 0.0,
                        "model_fact_consistency_rate": stats["model_fact_consistent"] / stats["valid"] if stats["valid"] else 0.0,
                        "final_fact_consistency_rate": stats["final_fact_consistent"] / stats["evaluations"] if stats["evaluations"] else 1.0,
                        "model_boundary_preservation_rate": stats["model_boundary_preserved"] / stats["valid"] if stats["valid"] else 0.0,
                        "final_boundary_preservation_rate": stats["final_boundary_preserved"] / stats["evaluations"] if stats["evaluations"] else 1.0,
                        "false_safe_assertions": stats["false_safe_assertions"],
                    }
                    for category, stats in sorted(category_stats.items())
                },
            }
        )
    return {
        "schema_version": "security-triage-llm-evaluation/v2",
        "dataset": str(_resolve_dataset(dataset_path)),
        "prompt_version": "security-triage-report/v2",
        "repetitions": repetitions,
        "candidates": outputs,
        "safety_note": "LLM output is accepted only after citation and not-executed boundary validation; rejected output falls back to deterministic report.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="examples/fixtures/security_triage_goldens.json")
    parser.add_argument(
        "--candidates",
        default=os.environ.get("SECURITY_TRIAGE_LLM_CANDIDATES", "deepseek"),
        help="comma-separated provider[:model] candidates",
    )
    parser.add_argument("--repetitions", type=int, default=int(os.environ.get("SECURITY_TRIAGE_LLM_REPETITIONS", "2")), choices=(1, 2, 3))
    args = parser.parse_args()
    if not os.environ.get("DEEPSEEK_API_KEY") and not os.environ.get("OPENAI_API_KEY") and not os.environ.get("LLM_API_KEY"):
        raise SystemExit("No API key configured; set DEEPSEEK_API_KEY, OPENAI_API_KEY, or LLM_API_KEY")
    print(json.dumps(evaluate(args.dataset, [item.strip() for item in args.candidates.split(",") if item.strip()], args.repetitions), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
