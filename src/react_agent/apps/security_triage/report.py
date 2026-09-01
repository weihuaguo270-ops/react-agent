"""Citation-based Markdown report renderer."""
from __future__ import annotations

from typing import Any


def render_report(case: dict[str, Any]) -> str:
    lines = [
        "# Security Triage Report",
        "",
        *([f"- Case ID: `{case['case_id']}` · version `{case['version']}`"] if case.get("case_id") else []),
        f"- Review state: **{case['status']}**",
        f"- Intelligence mode: `{case['mode']}`",
        f"- Evidence time boundary: `{case['evidence_as_of']}`",
        "",
        "## CVE and KEV findings",
    ]
    for cve in case["cves"]:
        cid = cve["citation_id"]
        if not cve["found"]:
            lines.append(f"- **{cve['cve_id']}**: not present in the bounded lookup result; do not interpret as nonexistent. [{cid}]")
            continue
        kev = next(item for item in case["kev"] if item["cve_id"] == cve["cve_id"])
        kev_text = "listed" if kev["listed"] else "not listed in this evidence boundary"
        lines.append(
            f"- **{cve['cve_id']}**: {cve['severity']} / CVSS {cve.get('cvss_score')}; "
            f"CISA KEV: **{kev_text}**. [{cid}] [{kev['citation_id']}]"
        )

    lines.extend(["", "## ATT&CK candidate mappings"])
    if not case["attack_mappings"]:
        lines.append("- No mapping candidate was produced from the available evidence.")
    for mapping in case["attack_mappings"]:
        lines.append(
            f"- **{mapping['cve_id']} -> {mapping['technique_id']} {mapping['technique_name']}** "
            f"({mapping['confidence']} confidence, **inferred / non-authoritative**): "
            f"{mapping['rationale']} [{mapping['citation_id']}]"
        )

    lines.extend(["", "## Asset and SBOM correlation"])
    if not case.get("assets"):
        lines.append("- No organization asset/SBOM evidence was supplied; asset impact remains unknown.")
    for item in case.get("asset_matches") or []:
        if not item["matched"]:
            supplied_ids = [str(asset.get("asset_id")) for asset in case.get("assets") or [] if asset.get("asset_id")]
            checked = f" Checked asset IDs: {', '.join(supplied_ids)}." if supplied_ids else ""
            lines.append(
                f"- **{item['cve_id']}**: no explicit match in supplied evidence.{checked} "
                "This is not an unaffected verdict."
            )
            continue
        for match in item["matches"]:
            lines.append(
                f"- **{item['cve_id']} -> {match['asset_id']} / {match['component_name']} {match['component_version']}** "
                f"(criticality={match['criticality']}, internet_exposed={str(match['internet_exposed']).lower()}). "
                f"Request-supplied SBOM declaration [{match['citation_id']}]"
            )

    lines.extend(["", "## IOC enrichment"])
    if not case["iocs"]:
        lines.append("- No IOC supplied.")
    for item in case["iocs"]:
        malicious = "unknown" if item.get("malicious") is None else str(item["malicious"]).lower()
        lines.append(
            f"- **{item['ioc']}** ({item['ioc_type']}): `{item['verdict']}`, malicious={malicious}. "
            f"{item['summary']} [{item['citation_id']}]"
        )

    lines.extend(["", "## Suggested actions (not executed)"])
    for action in case["recommendations"]:
        refs = " ".join(f"[{cid}]" for cid in action["citation_ids"])
        lines.append(f"- **{action['priority']}**: {action['action']} `{action['execution']}` {refs}".rstrip())

    review = case["review"]
    lines.extend(["", "## Human review"])
    if case["status"] == "pending_review":
        lines.append("- Pending analyst review. No recommendation is authorized for execution.")
    else:
        lines.append(f"- Decision: **{case['status']}** by `{review['reviewer']}`. Notes: {review.get('notes') or '(none)'}")

    lines.extend(["", "## Evidence boundaries"])
    lines.extend(f"- {item}" for item in case["limitations"])
    lines.extend(["", "## References"])
    for citation in case["citations"]:
        lines.append(f"- [{citation['id']}] {citation['title']}: {citation['url']} (retrieved {citation['retrieved_at']})")
    return "\n".join(lines)
