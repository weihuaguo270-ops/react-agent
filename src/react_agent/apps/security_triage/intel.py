"""Public-intelligence providers for Security Triage Agent."""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import classify_ioc

_SNAPSHOT_PATH = Path(__file__).with_name("public_intel_snapshot.json")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_snapshot() -> dict[str, Any]:
    return json.loads(_SNAPSHOT_PATH.read_text(encoding="utf-8"))


class SnapshotIntel:
    """Small deterministic public-intelligence fixture for demos and tests."""

    mode = "offline_snapshot"

    def __init__(self) -> None:
        self.data = _load_snapshot()
        self.snapshot_at = str(self.data["snapshot_at"])

    def citation(self, citation_id: str) -> dict[str, Any]:
        source = dict(self.data["citations"][citation_id])
        return {"id": citation_id, **source}

    def lookup_cve(self, cve_id: str) -> dict[str, Any]:
        value = self.data["cves"].get(cve_id)
        if value is None:
            return {
                "cve_id": cve_id,
                "found": False,
                "lookup_status": "not_in_snapshot",
                "citation_id": "NVD-API",
            }
        return {"cve_id": cve_id, "found": True, **value}

    def check_kev(self, cve_id: str) -> dict[str, Any]:
        value = self.data["kev"].get(cve_id)
        if value is None:
            return {
                "cve_id": cve_id,
                "listed": False,
                "lookup_status": "not_listed_in_snapshot",
                "citation_id": "CISA-KEV",
            }
        return {"cve_id": cve_id, "listed": True, **value}

    def enrich_ioc(self, ioc: str) -> dict[str, Any]:
        value = self.data["iocs"].get(ioc.lower())
        if value is None:
            return {
                "ioc": ioc,
                "ioc_type": classify_ioc(ioc),
                "found": False,
                "verdict": "not_observed_in_snapshot",
                "malicious": None,
                "confidence": "unknown",
                "summary": "No enrichment record exists in the bounded offline fixture; this is not a clean verdict.",
                "source": "ThreatFox fixture boundary",
                "citation_id": "THREATFOX",
            }
        return {"ioc": ioc, "found": True, **value}


class LivePublicIntel(SnapshotIntel):
    """Opt-in live lookups against fixed, read-only public endpoints."""

    mode = "live_public_sources"

    def __init__(self) -> None:
        super().__init__()
        self.snapshot_at = _now()
        self._kev: dict[str, dict[str, Any]] | None = None
        self._live_citations: dict[str, dict[str, Any]] = {}

    def citation(self, citation_id: str) -> dict[str, Any]:
        if citation_id in self._live_citations:
            return {"id": citation_id, **self._live_citations[citation_id]}
        return super().citation(citation_id)

    def _get_json(self, url: str, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            url,
            data=data,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "react-agent-security-triage/0.10",
            },
            method="POST" if payload is not None else "GET",
        )
        timeout = float(os.environ.get("REACT_AGENT_SECURITY_TIMEOUT", "10"))
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def lookup_cve(self, cve_id: str) -> dict[str, Any]:
        url = "https://services.nvd.nist.gov/rest/json/cves/2.0?" + urllib.parse.urlencode({"cveId": cve_id})
        data = self._get_json(url)
        rows = data.get("vulnerabilities") or []
        citation_id = f"NVD-{cve_id}"
        self._live_citations[citation_id] = {
            "title": f"NVD: {cve_id}",
            "url": f"https://nvd.nist.gov/vuln/detail/{cve_id}",
            "retrieved_at": _now(),
        }
        if not rows:
            return {"cve_id": cve_id, "found": False, "lookup_status": "not_found", "citation_id": citation_id}
        cve = rows[0].get("cve") or {}
        description = next((x.get("value", "") for x in cve.get("descriptions") or [] if x.get("lang") == "en"), "")
        metrics = cve.get("metrics") or {}
        cvss = {}
        for key in ("cvssMetricV40", "cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
            if metrics.get(key):
                cvss = (metrics[key][0].get("cvssData") or {})
                break
        cwes = [
            item.get("value")
            for weakness in cve.get("weaknesses") or []
            for item in weakness.get("description") or []
            if str(item.get("value") or "").startswith("CWE-")
        ]
        return {
            "cve_id": cve_id,
            "found": True,
            "description": description,
            "published": str(cve.get("published") or "")[:10],
            "severity": cvss.get("baseSeverity") or "UNKNOWN",
            "cvss_score": cvss.get("baseScore"),
            "cwes": list(dict.fromkeys(cwes)),
            "citation_id": citation_id,
        }

    def check_kev(self, cve_id: str) -> dict[str, Any]:
        if self._kev is None:
            url = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
            data = self._get_json(url)
            self._kev = {str(row.get("cveID")): row for row in data.get("vulnerabilities") or []}
            self._live_citations["CISA-KEV-LIVE"] = {
                "title": "CISA Known Exploited Vulnerabilities Catalog",
                "url": "https://www.cisa.gov/known-exploited-vulnerabilities-catalog",
                "retrieved_at": _now(),
            }
        value = self._kev.get(cve_id)
        if value is None:
            return {"cve_id": cve_id, "listed": False, "lookup_status": "not_listed", "citation_id": "CISA-KEV-LIVE"}
        return {
            "cve_id": cve_id,
            "listed": True,
            "date_added": value.get("dateAdded"),
            "due_date": value.get("dueDate"),
            "known_ransomware_campaign_use": value.get("knownRansomwareCampaignUse"),
            "required_action": value.get("requiredAction"),
            "citation_id": "CISA-KEV-LIVE",
        }

    def enrich_ioc(self, ioc: str) -> dict[str, Any]:
        data = self._get_json(
            "https://threatfox-api.abuse.ch/api/v1/",
            payload={"query": "search_ioc", "search_term": ioc},
        )
        citation_id = "THREATFOX-LIVE"
        self._live_citations[citation_id] = {
            "title": "ThreatFox IOC database",
            "url": "https://threatfox.abuse.ch/",
            "retrieved_at": _now(),
        }
        rows = data.get("data") if isinstance(data.get("data"), list) else []
        if not rows:
            return {
                "ioc": ioc,
                "ioc_type": classify_ioc(ioc),
                "found": False,
                "verdict": "not_found",
                "malicious": None,
                "confidence": "unknown",
                "summary": "ThreatFox returned no matching record; absence is not a clean verdict.",
                "source": "ThreatFox",
                "citation_id": citation_id,
            }
        row = rows[0]
        return {
            "ioc": ioc,
            "ioc_type": row.get("ioc_type") or classify_ioc(ioc),
            "found": True,
            "verdict": "reported_malicious",
            "malicious": True,
            "confidence": "source_reported",
            "summary": f"ThreatFox association: {row.get('threat_type') or 'unknown'} / {row.get('malware_printable') or 'unknown malware'}.",
            "source": "ThreatFox",
            "first_seen": row.get("first_seen"),
            "last_seen": row.get("last_seen"),
            "citation_id": citation_id,
        }


def get_intel_provider() -> SnapshotIntel:
    enabled = os.environ.get("REACT_AGENT_SECURITY_LIVE", "").strip().lower() in {"1", "true", "yes", "on"}
    return LivePublicIntel() if enabled else SnapshotIntel()
