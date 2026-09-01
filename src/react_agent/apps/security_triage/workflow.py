"""Deterministic, read-only security triage workflow."""
from __future__ import annotations

from typing import Any

from .assets import correlate_assets
from .attack_mapping import infer_attack_mappings
from .episode import build_evaluation_episode
from .intel import SnapshotIntel, get_intel_provider
from .llm_report import generate_llm_report
from .models import TriageRequest
from .report import render_report


def _recommendations(
    cves: list[dict[str, Any]],
    kev: list[dict[str, Any]],
    iocs: list[dict[str, Any]],
    asset_matches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    kev_by_cve = {item["cve_id"]: item for item in kev}
    assets_by_cve = {item["cve_id"]: item for item in asset_matches}
    for cve in cves:
        if not cve.get("found"):
            continue
        kev_item = kev_by_cve[cve["cve_id"]]
        asset_item = assets_by_cve[cve["cve_id"]]
        exposed = any(item["internet_exposed"] for item in asset_item["matches"])
        if kev_item["listed"] and asset_item["matched"] and exposed:
            priority = "critical"
        elif kev_item["listed"] or asset_item["matched"]:
            priority = "urgent"
        else:
            priority = "risk_based"
        citations = [cve["citation_id"], kev_item["citation_id"]]
        citations.extend(item["citation_id"] for item in asset_item["matches"])
        asset_context = (
            f" Evidence declares {asset_item['asset_count']} in-scope asset(s)."
            if asset_item["matched"]
            else " No supplied asset evidence confirms exposure."
        )
        recommendations.append(
            {
                "id": f"REC-{len(recommendations) + 1}",
                "priority": priority,
                "action": f"Confirm whether {cve['cve_id']} affects in-scope assets using inventory/SBOM evidence, then plan the vendor-recommended update through change control.{asset_context}",
                "requires_human_approval": True,
                "execution": "not_executed",
                "citation_ids": citations,
            }
        )
    for item in iocs:
        if item.get("malicious") is True:
            recommendations.append(
                {
                    "id": f"REC-{len(recommendations) + 1}",
                    "priority": "high",
                    "action": f"Search authorized telemetry for {item['ioc']}, validate time and asset context, and escalate confirmed matches to the incident process.",
                    "requires_human_approval": True,
                    "execution": "not_executed",
                    "citation_ids": [item["citation_id"]],
                }
            )
    recommendations.append(
        {
            "id": f"REC-{len(recommendations) + 1}",
            "priority": "required_review",
            "action": "An analyst must validate asset relevance, source freshness, false-positive risk, and organizational policy before any containment or remediation.",
            "requires_human_approval": True,
            "execution": "not_executed",
            "citation_ids": [],
        }
    )
    return recommendations


def run_triage(
    body: dict[str, Any],
    provider: SnapshotIntel | None = None,
    *,
    episode_id: str | None = None,
    split: str = "dev",
    expected: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request = TriageRequest.from_body(body)
    intel = provider or get_intel_provider()
    cves = [intel.lookup_cve(cve_id) for cve_id in request.cve_ids]
    kev = [intel.check_kev(cve_id) for cve_id in request.cve_ids]
    attack_mappings = [mapping for cve in cves if cve.get("found") for mapping in infer_attack_mappings(cve)]
    iocs = [intel.enrich_ioc(ioc) for ioc in request.iocs]
    asset_matches, asset_citations = correlate_assets(
        request.cve_ids, request.assets, intel.snapshot_at
    )
    recommendations = _recommendations(cves, kev, iocs, asset_matches)

    citation_ids: list[str] = []
    for item in [*cves, *kev, *attack_mappings, *iocs]:
        citation_id = item.get("citation_id")
        if citation_id and citation_id not in citation_ids:
            citation_ids.append(citation_id)
    for recommendation in recommendations:
        for citation_id in recommendation["citation_ids"]:
            if citation_id not in citation_ids:
                citation_ids.append(citation_id)

    status = request.review.decision if request.review else "pending_review"
    review = {
        "required": True,
        "decision": status,
        "reviewer": request.review.reviewer if request.review else None,
        "notes": request.review.notes if request.review else "",
    }
    limitations = [
        "This application performs no scanning, exploitation, blocking, containment, or remediation.",
        "ATT&CK mappings are analyst-review hypotheses inferred from CWE/description, not authoritative CVE-to-ATT&CK mappings.",
        "A missing CVE, KEV, or IOC record only means absent from the selected evidence boundary; it is not a clean or safe verdict.",
        "Public intelligence does not establish whether a vulnerability or indicator is relevant to the organization's assets.",
    ]
    case = {
        "schema_version": "security-triage/v1",
        "status": status,
        "mode": intel.mode,
        "evidence_as_of": intel.snapshot_at,
        "read_only": True,
        "cves": cves,
        "kev": kev,
        "attack_mappings": attack_mappings,
        "iocs": iocs,
        "recommendations": recommendations,
        "assets": request.assets,
        "sbom": request.sbom,
        "asset_matches": asset_matches,
        "citations": [intel.citation(citation_id) for citation_id in citation_ids if not citation_id.startswith("ASSET-")]
        + asset_citations,
        "review": review,
        "limitations": limitations,
        "executed_actions": [],
        "trace": [
            {"step": 1, "node": "parse_request", "status": "completed"},
            {"step": 2, "node": "public_intelligence", "status": "completed"},
            {"step": 3, "node": "asset_correlation", "status": "completed"},
            {"step": 4, "node": "attack_inference", "status": "completed"},
            {"step": 5, "node": "report_validation", "status": "completed"},
            {"step": 6, "node": "human_review_gate", "status": "pending" if status == "pending_review" else "completed"},
        ],
    }
    deterministic_answer = render_report(case)
    llm_answer, llm_metadata = generate_llm_report(case)
    case["llm_report"] = llm_metadata
    if llm_answer:
        case["trace"].append({"step": 7, "node": "llm_report_editor", "status": "completed"})
        result = {"answer": llm_answer, "case": case}
        result["episode"] = build_evaluation_episode(
            body, result, episode_id=episode_id, split=split, expected=expected
        )
        return result
    case["trace"].append(
        {
            "step": 7,
            "node": "llm_report_editor",
            "status": "fallback",
            "failure": llm_metadata.get("failure"),
        }
    )
    result = {"answer": deterministic_answer, "case": case}
    result["episode"] = build_evaluation_episode(
        body, result, episode_id=episode_id, split=split, expected=expected
    )
    return result
