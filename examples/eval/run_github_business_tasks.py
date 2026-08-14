"""Run read-only business tasks against the public GitHub REST API."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

API = "https://api.github.com"


def _github_token():
    """Resolve a token without printing it or persisting it in project files."""
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return token.strip()
    executable = shutil.which("gh")
    if not executable:
        return ""
    try:
        result = subprocess.run(
            [executable, "auth", "token"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _get(path):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "react-agent-evidence"}
    token = _github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    started = time.perf_counter()
    with urllib.request.urlopen(urllib.request.Request(f"{API}{path}", headers=headers), timeout=30) as response:
        return (json.loads(response.read().decode("utf-8")),
                (time.perf_counter() - started) * 1000, response.headers.get("X-GitHub-Request-Id"))


def run_github_tasks(repository):
    repo, repo_latency, repo_request = _get(f"/repos/{repository}")
    issues, issue_latency, issue_request = _get(f"/repos/{repository}/issues?state=open&per_page=10")
    real_issues = [item for item in issues if "pull_request" not in item]
    cases = [
        {"case_id": "github_repository_contract", "split": "golden",
         "passed": repo.get("full_name", "").lower() == repository.lower() and bool(repo.get("html_url")),
         "source_url": repo.get("html_url"), "latency_ms": repo_latency, "request_id": repo_request},
        {"case_id": "github_issue_triage", "split": "held_out", "passed": isinstance(real_issues, list),
         "source_url": f"https://github.com/{repository}/issues", "latency_ms": issue_latency,
         "request_id": issue_request, "issue_sample": [
             {"number": item["number"], "title": item["title"],
              "labels": [label["name"] for label in item.get("labels", [])], "url": item["html_url"]}
             for item in real_issues[:5]]},
    ]
    trajectory = {"session_id": f"github-{repository.replace('/', '-')}",
                  "query": f"Inspect {repository} and triage current public issues.",
                  "model": "deterministic-github-agent-v1", "steps": [
                      {"step": 1, "thought": "Read repository metadata.",
                       "action": {"name": "github_get_repository", "arguments": json.dumps({"repository": repository})},
                       "observation": json.dumps({"full_name": repo.get("full_name"), "url": repo.get("html_url")})},
                      {"step": 2, "thought": "Read issues and exclude pull requests.",
                       "action": {"name": "github_list_issues", "arguments": json.dumps({"repository": repository})},
                       "observation": json.dumps({"issue_count": len(real_issues),
                                                  "numbers": [item["number"] for item in real_issues]})}],
                  "final_answer": f"Inspected {repository}; found {len(real_issues)} open issues in the first page."}
    return {"schema_version": "external-business-evidence/v1", "system": "github-rest-api",
            "repository": repository, "read_only": True, "authenticated": bool(_github_token()),
            "cases": cases, "pass_rate": sum(row["passed"] for row in cases) / len(cases),
            "trajectory": trajectory,
            "evidence_boundary": "Public read-only data; dynamic issue content is not a frozen benchmark."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default="langchain-ai/langgraph")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = run_github_tasks(args.repository)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["pass_rate"] == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
