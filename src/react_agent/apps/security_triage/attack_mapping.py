"""Conservative ATT&CK inference rules.

ATT&CK describes adversary behavior, not vulnerabilities. These mappings are
hypotheses for analyst review and are never represented as authoritative facts.
"""
from __future__ import annotations

from typing import Any

_RULES = {
    "CWE-502": {
        "technique_id": "T1190",
        "technique_name": "Exploit Public-Facing Application",
        "confidence": "medium",
        "rationale": "CWE-502 plus remote exploitation language suggests exploitation of an exposed application.",
    },
    "CWE-79": {
        "technique_id": "T1059.007",
        "technique_name": "JavaScript/JScript",
        "confidence": "low",
        "rationale": "CWE-79 can involve attacker-controlled script execution, but deployment context is required.",
    },
}


def infer_attack_mappings(cve: dict[str, Any]) -> list[dict[str, Any]]:
    """Infer deduplicated ATT&CK candidates from CWE and CVE description."""
    mappings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for cwe in cve.get("cwes") or []:
        rule = _RULES.get(str(cwe).upper())
        if not rule or rule["technique_id"] in seen:
            continue
        technique_id = rule["technique_id"]
        seen.add(technique_id)
        mappings.append(
            {
                **rule,
                "cve_id": cve.get("cve_id"),
                "basis": {"cwe": cwe, "description_excerpt": str(cve.get("description") or "")[:180]},
                "mapping_type": "inferred",
                "authoritative": False,
                "citation_id": f"ATTACK-{technique_id.replace('.', '-')}",
            }
        )
    return mappings
