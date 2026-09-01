"""Normalize request-supplied asset/SBOM evidence and correlate it to CVEs."""
from __future__ import annotations

import re
from typing import Any

_CVE_RE = re.compile(r"^CVE-\d{4}-\d{4,7}$", re.IGNORECASE)
_CRITICALITIES = {"critical", "high", "medium", "low", "unknown"}


def _text(value: Any, field: str, *, required: bool = False, limit: int = 200) -> str:
    result = str(value or "").strip()
    if required and not result:
        raise ValueError(f"{field} is required")
    if len(result) > limit:
        raise ValueError(f"{field} exceeds {limit} characters")
    return result


def normalize_assets(value: Any) -> list[dict[str, Any]]:
    """Validate bounded, organization-supplied asset and component evidence."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("assets must be an array")
    if len(value) > 100:
        raise ValueError("one request supports at most 100 assets")

    assets: list[dict[str, Any]] = []
    component_count = 0
    seen_asset_ids: set[str] = set()
    for asset_index, raw_asset in enumerate(value, start=1):
        if not isinstance(raw_asset, dict):
            raise ValueError(f"assets[{asset_index - 1}] must be an object")
        asset_id = _text(raw_asset.get("asset_id"), "asset_id", required=True, limit=100)
        if asset_id in seen_asset_ids:
            raise ValueError(f"duplicate asset_id: {asset_id}")
        seen_asset_ids.add(asset_id)
        criticality = _text(raw_asset.get("criticality") or "unknown", "criticality", limit=20).lower()
        if criticality not in _CRITICALITIES:
            raise ValueError(f"unsupported asset criticality: {criticality}")
        raw_components = raw_asset.get("components") or []
        if not isinstance(raw_components, list):
            raise ValueError(f"components for {asset_id} must be an array")

        components: list[dict[str, Any]] = []
        for component_index, raw_component in enumerate(raw_components, start=1):
            if not isinstance(raw_component, dict):
                raise ValueError(f"component {component_index} for {asset_id} must be an object")
            component_count += 1
            if component_count > 500:
                raise ValueError("one request supports at most 500 components")
            cve_values = raw_component.get("cve_ids") or []
            if not isinstance(cve_values, list):
                raise ValueError(f"component cve_ids for {asset_id} must be an array")
            cve_ids: list[str] = []
            for raw_cve in cve_values:
                cve_id = str(raw_cve).strip().upper()
                if not _CVE_RE.fullmatch(cve_id):
                    raise ValueError(f"invalid component CVE ID: {raw_cve}")
                if cve_id not in cve_ids:
                    cve_ids.append(cve_id)
            components.append(
                {
                    "component_id": _text(
                        raw_component.get("component_id") or f"component-{component_index}",
                        "component_id",
                        limit=100,
                    ),
                    "name": _text(raw_component.get("name"), "component name", required=True),
                    "version": _text(raw_component.get("version"), "component version", limit=100),
                    "purl": _text(raw_component.get("purl"), "component purl", limit=500),
                    "cpe": _text(raw_component.get("cpe"), "component cpe", limit=500),
                    "cve_ids": cve_ids,
                    "source": _text(raw_component.get("source") or "request_sbom", "component source", limit=100),
                }
            )
        assets.append(
            {
                "asset_id": asset_id,
                "name": _text(raw_asset.get("name") or asset_id, "asset name"),
                "criticality": criticality,
                "internet_exposed": bool(raw_asset.get("internet_exposed", False)),
                "owner": _text(raw_asset.get("owner"), "asset owner", limit=200),
                "components": components,
            }
        )
    return assets


def correlate_assets(
    cve_ids: list[str], assets: list[dict[str, Any]], evidence_as_of: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return per-CVE matches and citations for explicit SBOM-to-CVE declarations."""
    results: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    for cve_id in cve_ids:
        matches: list[dict[str, Any]] = []
        for asset_index, asset in enumerate(assets, start=1):
            for component_index, component in enumerate(asset["components"], start=1):
                if cve_id not in component["cve_ids"]:
                    continue
                citation_id = f"ASSET-{asset_index}-COMPONENT-{component_index}"
                matches.append(
                    {
                        "asset_id": asset["asset_id"],
                        "asset_name": asset["name"],
                        "criticality": asset["criticality"],
                        "internet_exposed": asset["internet_exposed"],
                        "owner": asset["owner"],
                        "component_id": component["component_id"],
                        "component_name": component["name"],
                        "component_version": component["version"],
                        "evidence_type": "declared_sbom_cve",
                        "citation_id": citation_id,
                    }
                )
                if not any(item["id"] == citation_id for item in citations):
                    citations.append(
                        {
                            "id": citation_id,
                            "title": f"Request-supplied SBOM evidence for {asset['asset_id']} / {component['name']}",
                            "url": f"urn:react-agent:asset:{asset_index}:component:{component_index}",
                            "retrieved_at": evidence_as_of,
                            "source_type": "organization_supplied",
                        }
                    )
        results.append(
            {
                "cve_id": cve_id,
                "matched": bool(matches),
                "asset_count": len({item["asset_id"] for item in matches}),
                "matches": matches,
                "evidence_boundary": (
                    "Matches rely on request-supplied component cve_ids; component versions were not independently evaluated."
                    if matches
                    else "No request-supplied SBOM component declared this CVE; this is not proof that assets are unaffected."
                ),
            }
        )
    return results, citations
