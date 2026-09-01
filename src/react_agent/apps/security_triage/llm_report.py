"""Guarded LLM report generation over structured, citation-bound evidence."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from typing import Any, Callable

PROMPT_VERSION = "security-triage-report/v2"
_CITATION_RE = re.compile(r"\[([A-Z0-9][A-Z0-9_.-]{1,80})\]")


def _enabled() -> bool:
    return os.environ.get("REACT_AGENT_SECURITY_LLM", "").strip().lower() in {"1", "true", "yes", "on"}


def _evidence_payload(case: dict[str, Any]) -> dict[str, Any]:
    """Keep prompt input limited to structured facts and evidence IDs."""
    return {
        "cves": case.get("cves", []),
        "kev": case.get("kev", []),
        "attack_mappings": case.get("attack_mappings", []),
        "iocs": case.get("iocs", []),
        "assets": case.get("assets", []),
        "sbom": case.get("sbom"),
        "asset_matches": case.get("asset_matches", []),
        "recommendations": case.get("recommendations", []),
        "citations": case.get("citations", []),
        "limitations": case.get("limitations", []),
    }


def _prompt(case: dict[str, Any]) -> str:
    evidence = json.dumps(_evidence_payload(case), ensure_ascii=False, sort_keys=True)
    return (
        "You are a security analyst report editor. Use ONLY the JSON evidence below. "
        "Do not invent CVEs, asset impact, ATT&CK mappings, IOC verdicts, dates, or actions. "
        "Preserve the distinction between fact, inferred mapping, recommendation, and unknown. "
        "Every factual statement must include one citation ID exactly as supplied in citations. "
        "Preserve CVE IDs, asset IDs, IOC strings, and machine-readable verdict labels exactly as supplied. "
        "For an asset with no match, name every supplied asset_id and state that no explicit match was found. "
        "For every IOC, include the original IOC string and its exact verdict label from the evidence. "
        "All recommendations must say not executed and require human approval. "
        "Return JSON only with exactly these top-level fields: claims, recommendations, limitations. "
        "claims is an array of objects {text, type, citation_ids}; type must be fact, inference, or unknown. "
        "Every fact/inference claim must have at least one citation_ids value from the supplied citations. "
        "recommendations is an array of {text, citation_ids, execution, requires_human_approval}; "
        "execution must be not_executed and requires_human_approval must be true. "
        "Do not include Markdown fences or any fields outside this schema.\n\n"
        f"Evidence JSON:\n{evidence}"
    )


def _allowed_citations(case: dict[str, Any]) -> set[str]:
    return {str(item.get("id")) for item in case.get("citations", [])}


def _parse_json(output: str) -> dict[str, Any] | None:
    text = output.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.DOTALL).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _render_structured(document: dict[str, Any]) -> str:
    lines = ["# Security Triage LLM Report", "", "## Findings"]
    for claim in document["claims"]:
        refs = " ".join(f"[{cid}]" for cid in claim["citation_ids"])
        lines.append(f"- **{claim['type']}**: {claim['text']} {refs}".rstrip())
    lines.extend(["", "## Recommendations"])
    for recommendation in document["recommendations"]:
        refs = " ".join(f"[{cid}]" for cid in recommendation["citation_ids"])
        lines.append(
            f"- {recommendation['text']} `not_executed` (human approval required) {refs}".rstrip()
        )
    lines.extend(["", "## Limitations"])
    lines.extend(f"- {item}" for item in document["limitations"])
    return "\n".join(lines)


def _validate_structured(document: dict[str, Any], case: dict[str, Any]) -> tuple[str | None, str]:
    if set(document) != {"claims", "recommendations", "limitations"}:
        return None, "structured_schema_fields_invalid"
    claims = document.get("claims")
    recommendations = document.get("recommendations")
    limitations = document.get("limitations")
    if not isinstance(claims, list) or not isinstance(recommendations, list) or not isinstance(limitations, list):
        return None, "structured_schema_types_invalid"
    allowed = _allowed_citations(case)
    normalized_claims: list[dict[str, Any]] = []
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict) or set(claim) != {"text", "type", "citation_ids"}:
            return None, f"structured_claim_invalid:{index}"
        if not isinstance(claim["text"], str) or claim["type"] not in {"fact", "inference", "unknown"}:
            return None, f"structured_claim_fields_invalid:{index}"
        citation_ids = claim["citation_ids"]
        if not isinstance(citation_ids, list) or any(not isinstance(item, str) for item in citation_ids):
            return None, f"structured_claim_citations_invalid:{index}"
        unknown = set(citation_ids) - allowed
        if unknown:
            return None, f"unknown_citation_ids:{','.join(sorted(unknown))}"
        if claim["type"] in {"fact", "inference"} and not citation_ids:
            return None, f"structured_claim_missing_citation:{index}"
        normalized_claims.append({"text": claim["text"].strip(), "type": claim["type"], "citation_ids": citation_ids})

    normalized_recommendations: list[dict[str, Any]] = []
    for index, recommendation in enumerate(recommendations):
        required = {"text", "citation_ids", "execution", "requires_human_approval"}
        if not isinstance(recommendation, dict) or set(recommendation) != required:
            return None, f"structured_recommendation_invalid:{index}"
        citation_ids = recommendation["citation_ids"]
        if not isinstance(citation_ids, list) or any(not isinstance(item, str) for item in citation_ids):
            return None, f"structured_recommendation_citations_invalid:{index}"
        unknown = set(citation_ids) - allowed
        if unknown:
            return None, f"unknown_citation_ids:{','.join(sorted(unknown))}"
        if recommendation["execution"] != "not_executed" or recommendation["requires_human_approval"] is not True:
            return None, f"structured_recommendation_boundary_invalid:{index}"
        normalized_recommendations.append(
            {
                "text": str(recommendation["text"]).strip(),
                "citation_ids": citation_ids,
                "execution": "not_executed",
                "requires_human_approval": True,
            }
        )
    if any(not isinstance(item, str) or not item.strip() for item in limitations):
        return None, "structured_limitations_invalid"
    normalized = {
        "claims": normalized_claims,
        "recommendations": normalized_recommendations,
        "limitations": [item.strip() for item in limitations],
    }
    return _render_structured(normalized), ""


def _validate_markdown(output: str, case: dict[str, Any]) -> tuple[bool, str]:
    if not isinstance(output, str) or not output.strip():
        return False, "empty_model_output"
    allowed = _allowed_citations(case)
    cited = set(_CITATION_RE.findall(output))
    unknown = cited - allowed
    if unknown:
        return False, f"unknown_citation_ids:{','.join(sorted(unknown))}"
    if not cited and (case.get("cves") or case.get("iocs") or case.get("asset_matches")):
        return False, "model_output_has_no_citations"
    lowered = output.lower()
    if "not executed" not in lowered and "not_executed" not in lowered:
        return False, "model_output_dropped_non_execution_boundary"
    return True, ""


def _validate(output: str, case: dict[str, Any]) -> tuple[str | None, str, str]:
    """Return rendered accepted output, failure code, and source format."""
    structured = _parse_json(output)
    if structured is not None:
        rendered, failure = _validate_structured(structured, case)
        if rendered is None:
            return None, failure, "json"
        return rendered, "", "json"
    valid, failure = _validate_markdown(output, case)
    return (output.strip() if valid else None), failure, "markdown"


def _repair_prompt(case: dict[str, Any], original: str, failure: str) -> str:
    allowed = sorted(_allowed_citations(case))
    return (
        "Repair the JSON report below without changing its factual text. Return JSON only with fields "
        "claims, recommendations, limitations. Add only citation_ids selected from the allowed list, "
        "and ensure every fact/inference has a citation. Every recommendation must use execution="
        "not_executed and requires_human_approval=true. Do not invent facts or citations. "
        f"Validation failure: {failure}. Allowed citation IDs: {json.dumps(allowed)}.\n"
        f"Original report JSON or text:\n{original[:12000]}"
    )


def _claim_texts(document: dict[str, Any] | None) -> list[str] | None:
    if not isinstance(document, dict) or not isinstance(document.get("claims"), list):
        return None
    texts = []
    for claim in document["claims"]:
        if not isinstance(claim, dict) or not isinstance(claim.get("text"), str):
            return None
        texts.append(claim["text"].strip())
    return texts


def generate_llm_report(
    case: dict[str, Any],
    *,
    llm: Any | None = None,
    chat: Callable[..., dict[str, Any]] | None = None,
) -> tuple[str | None, dict[str, Any]]:
    """Generate a citation-bound report only when explicitly enabled."""
    evidence = _evidence_payload(case)
    digest = hashlib.sha256(json.dumps(evidence, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    metadata: dict[str, Any] = {
        "enabled": _enabled(),
        "prompt_version": PROMPT_VERSION,
        "evidence_sha256": digest,
        "provider": None,
        "model": None,
        "fallback": True,
        "failure": None,
        "attempts": 0,
        "repair_used": False,
        "output_format": None,
    }
    if not metadata["enabled"] and chat is None and llm is None:
        metadata["failure"] = "llm_disabled"
        return None, metadata
    try:
        def request_model(prompt: str) -> dict[str, Any] | str:
            if chat is None:
                if llm is None:
                    from react_agent.llm import get_default_llm

                    client = get_default_llm()
                else:
                    client = llm
                if client is None:
                    raise RuntimeError("default LLM unavailable")
                metadata["provider"] = getattr(client, "provider_name", None)
                metadata["model"] = getattr(client, "model", None)
                return client.chat(
                    [
                        {"role": "system", "content": "You edit evidence-bound security reports."},
                        {"role": "user", "content": prompt},
                    ],
                    tool_defs=None,
                    temperature=0,
                    max_tokens=1800,
                )
            return chat(prompt, case)

        response = request_model(_prompt(case))
        metadata["attempts"] = 1
        output = response.get("content", "") if isinstance(response, dict) else str(response)
        accepted, failure, output_format = _validate(output, case)
        if accepted is None and failure not in {"empty_model_output", "model_output_dropped_non_execution_boundary"}:
            metadata["repair_used"] = True
            original_document = _parse_json(output)
            repair_response = request_model(_repair_prompt(case, output, failure))
            metadata["attempts"] = 2
            repaired = repair_response.get("content", "") if isinstance(repair_response, dict) else str(repair_response)
            repaired_document = _parse_json(repaired)
            original_claims = _claim_texts(original_document)
            repaired_claims = _claim_texts(repaired_document)
            if original_claims is not None and repaired_claims is not None and original_claims != repaired_claims:
                accepted, failure, output_format = None, "repair_changed_factual_claims", "json"
            else:
                accepted, failure, output_format = _validate(repaired, case)
        if accepted is None:
            metadata["failure"] = failure
            return None, metadata
        metadata["fallback"] = False
        metadata["output_format"] = output_format
        return accepted, metadata
    except Exception as exc:  # LLM is an optional presentation layer; deterministic report remains available.
        metadata["failure"] = f"llm_exception:{str(exc)[:240]}"
        return None, metadata


def compare_report_models(
    case: dict[str, Any],
    candidates: dict[str, Callable[[str, dict[str, Any]], dict[str, Any]]],
) -> dict[str, Any]:
    """Run controlled candidate editors against identical evidence for model selection."""
    if not candidates:
        raise ValueError("at least one model candidate is required")
    results: list[dict[str, Any]] = []
    for model_name, chat in candidates.items():
        started = time.monotonic()
        output, metadata = generate_llm_report(case, chat=chat)
        elapsed_ms = round((time.monotonic() - started) * 1000, 3)
        results.append(
            {
                "model": str(model_name),
                "valid": output is not None,
                "elapsed_ms": elapsed_ms,
                "citation_bound": output is not None,
                "boundary_preserved": output is not None or metadata.get("failure") == "llm_disabled",
                "prompt_version": metadata["prompt_version"],
                "failure": metadata.get("failure"),
            }
        )
    valid = [item for item in results if item["valid"]]
    return {
        "schema_version": "security-triage-model-comparison/v1",
        "evidence_sha256": hashlib.sha256(
            json.dumps(_evidence_payload(case), ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest(),
        "candidate_count": len(results),
        "valid_count": len(valid),
        "results": results,
    }
