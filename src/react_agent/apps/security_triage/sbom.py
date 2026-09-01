"""Read-only CycloneDX SBOM adapter.

The adapter accepts an already-loaded document supplied by an authorized caller;
it never fetches URLs or reads arbitrary filesystem paths.
"""
from __future__ import annotations

from typing import Any


def assets_from_cyclonedx(
    document: dict[str, Any],
    *,
    asset_id: str,
    name: str | None = None,
    criticality: str = "unknown",
    internet_exposed: bool = False,
    owner: str = "",
) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise ValueError("CycloneDX document must be an object")
    if str(document.get("bomFormat") or "").lower() != "cyclonedx":
        raise ValueError("sbom.bomFormat must be CycloneDX")
    spec_version = str(document.get("specVersion") or "")
    if not spec_version or len(spec_version) > 20:
        raise ValueError("sbom.specVersion is required")
    raw_components = document.get("components") or []
    if not isinstance(raw_components, list) or len(raw_components) > 500:
        raise ValueError("CycloneDX components must be an array of at most 500 items")
    components: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_components, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"CycloneDX component {index} must be an object")
        vulnerabilities = raw.get("vulnerabilities") or []
        if not isinstance(vulnerabilities, list):
            raise ValueError(f"CycloneDX vulnerabilities for component {index} must be an array")
        cve_ids: list[str] = []
        for vulnerability in vulnerabilities:
            if not isinstance(vulnerability, dict):
                continue
            vuln_id = str(vulnerability.get("id") or "").strip().upper()
            if vuln_id.startswith("CVE-") and vuln_id not in cve_ids:
                cve_ids.append(vuln_id)
        components.append(
            {
                "component_id": str(raw.get("bom-ref") or f"cyclonedx-component-{index}")[:100],
                "name": str(raw.get("name") or "").strip()[:200],
                "version": str(raw.get("version") or "").strip()[:100],
                "purl": str(raw.get("purl") or "").strip()[:500],
                "cpe": str(raw.get("cpe") or "").strip()[:500],
                "cve_ids": cve_ids,
                "source": "cyclonedx_inline",
            }
        )
    return {
        "asset_id": asset_id,
        "name": name or asset_id,
        "criticality": criticality,
        "internet_exposed": bool(internet_exposed),
        "owner": owner,
        "components": components,
        "sbom": {"format": "CycloneDX", "spec_version": spec_version, "component_count": len(components)},
    }
