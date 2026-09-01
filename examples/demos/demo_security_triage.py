"""Run the deterministic Security Triage Agent MVP."""
from __future__ import annotations

from react_agent.apps.security_triage import run_triage


def main() -> None:
    result = run_triage(
        {
            "cve_ids": ["CVE-2021-44228"],
            "iocs": ["example.invalid", "8.8.8.8"],
        }
    )
    print(result["answer"])


if __name__ == "__main__":
    main()
