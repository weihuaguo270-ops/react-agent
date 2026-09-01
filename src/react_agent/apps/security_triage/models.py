"""Input normalization and review-state rules for security triage."""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from typing import Any

_CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.IGNORECASE)
_HASH_RE = re.compile(r"\b(?:[A-Fa-f0-9]{32}|[A-Fa-f0-9]{40}|[A-Fa-f0-9]{64})\b")
_DOMAIN_RE = re.compile(
    r"(?<![@\w-])(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+"
    r"(?:[a-zA-Z]{2,63}|invalid)(?![\w-])"
)


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        key = normalized.lower()
        if normalized and key not in seen:
            seen.add(key)
            result.append(normalized)
    return result


def classify_ioc(value: str) -> str:
    """Classify supported IOC syntax without making a threat assertion."""
    try:
        return "ipv4" if ipaddress.ip_address(value).version == 4 else "ipv6"
    except ValueError:
        pass
    if re.fullmatch(r"[A-Fa-f0-9]{32}", value):
        return "md5"
    if re.fullmatch(r"[A-Fa-f0-9]{40}", value):
        return "sha1"
    if re.fullmatch(r"[A-Fa-f0-9]{64}", value):
        return "sha256"
    if _DOMAIN_RE.fullmatch(value):
        return "domain"
    return "unknown"


@dataclass(frozen=True)
class ReviewInput:
    decision: str
    reviewer: str
    notes: str = ""

    @classmethod
    def from_value(cls, value: Any) -> "ReviewInput | None":
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("review must be an object")
        aliases = {
            "approve": "approved",
            "approved": "approved",
            "reject": "rejected",
            "rejected": "rejected",
        }
        raw = str(value.get("decision") or "").strip().lower()
        decision = aliases.get(raw)
        reviewer = str(value.get("reviewer") or "").strip()
        if decision is None:
            raise ValueError("review.decision must be approve or reject")
        if not reviewer:
            raise ValueError("review.reviewer is required for an explicit decision")
        return cls(decision=decision, reviewer=reviewer, notes=str(value.get("notes") or "").strip())


@dataclass(frozen=True)
class TriageRequest:
    cve_ids: list[str] = field(default_factory=list)
    iocs: list[str] = field(default_factory=list)
    assets: list[dict[str, Any]] = field(default_factory=list)
    sbom: dict[str, Any] | None = None
    review: ReviewInput | None = None

    @classmethod
    def from_body(cls, body: dict[str, Any]) -> "TriageRequest":
        message = str(body.get("message") or body.get("query") or "")
        explicit_cves = body.get("cve_ids") or []
        explicit_iocs = body.get("iocs") or []
        if not isinstance(explicit_cves, list) or not isinstance(explicit_iocs, list):
            raise ValueError("cve_ids and iocs must be arrays")

        cves = [str(v).upper() for v in explicit_cves]
        cves.extend(match.upper() for match in _CVE_RE.findall(message))

        iocs = [str(v) for v in explicit_iocs]
        message_without_cves = _CVE_RE.sub(" ", message)
        iocs.extend(_HASH_RE.findall(message_without_cves))
        for token in re.findall(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])", message_without_cves):
            try:
                ipaddress.ip_address(token)
                iocs.append(token)
            except ValueError:
                continue
        iocs.extend(_DOMAIN_RE.findall(message_without_cves))

        normalized_cves = _unique(cves)
        normalized_iocs = _unique(iocs)
        if len(normalized_cves) > 20 or len(normalized_iocs) > 50:
            raise ValueError("one request supports at most 20 CVEs and 50 IOCs")
        if not normalized_cves and not normalized_iocs:
            raise ValueError("provide at least one CVE ID or IOC")
        unsupported = [value for value in normalized_iocs if classify_ioc(value) == "unknown"]
        if unsupported:
            raise ValueError(f"unsupported IOC syntax: {unsupported[0]}")
        from .assets import normalize_assets
        from .sbom import assets_from_cyclonedx

        assets = normalize_assets(body.get("assets"))
        raw_sbom = body.get("sbom")
        sbom_asset = None
        if raw_sbom is not None:
            if not isinstance(raw_sbom, dict):
                raise ValueError("sbom must be an object")
            sbom_document = raw_sbom.get("document")
            sbom_asset_id = str(raw_sbom.get("asset_id") or "").strip()
            if not sbom_asset_id:
                raise ValueError("sbom.asset_id is required")
            sbom_asset = assets_from_cyclonedx(
                sbom_document,
                asset_id=sbom_asset_id,
                name=raw_sbom.get("name"),
                criticality=str(raw_sbom.get("criticality") or "unknown"),
                internet_exposed=bool(raw_sbom.get("internet_exposed", False)),
                owner=str(raw_sbom.get("owner") or ""),
            )
            assets.append(sbom_asset)

        return cls(
            cve_ids=normalized_cves,
            iocs=normalized_iocs,
            assets=assets,
            sbom=raw_sbom if isinstance(raw_sbom, dict) else None,
            review=ReviewInput.from_value(body.get("review")),
        )
