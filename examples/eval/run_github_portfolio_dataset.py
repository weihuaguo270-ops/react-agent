"""Build an auditable 50-task dataset from public GitHub repositories."""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

from examples.eval.run_github_business_tasks import _get, _github_token

REPOSITORIES = (
    "langchain-ai/langgraph", "openai/openai-agents-python",
    "modelcontextprotocol/python-sdk", "huggingface/transformers",
    "pytest-dev/pytest", "pallets/flask", "fastapi/fastapi",
    "psf/requests", "pydantic/pydantic", "encode/httpx",
)
TASK_FAMILIES = ("identity", "activity", "popularity", "technology", "governance")
SPLITS = {"dev": REPOSITORIES[:3], "golden": REPOSITORIES[3:7],
          "held_out": REPOSITORIES[7:]}


def _split_for(repository):
    return next((split for split, repositories in SPLITS.items()
                 if repository in repositories), "held_out")


def _case(repository, family, passed, source_url, latency_ms, request_id, answer):
    return {"case_id": f"github::{repository}::{family}", "repository": repository,
            "task_family": family, "split": _split_for(repository), "passed": bool(passed),
            "source_url": source_url, "latency_ms": round(latency_ms, 3),
            "request_id": request_id, "answer": answer}


def _run_repository(repository, cached=None):
    if cached:
        repo, repo_latency, repo_request = cached["payload"], cached["latency_ms"], cached["request_id"]
    else:
        repo, repo_latency, repo_request = _get(f"/repos/{repository}")
    source = repo.get("html_url") or f"https://github.com/{repository}"
    cases = [
        _case(repository, "identity", repo.get("full_name", "").lower() == repository.lower(),
              source, repo_latency, repo_request, {"full_name": repo.get("full_name")}),
        _case(repository, "activity", isinstance(repo.get("open_issues_count"), int)
              and bool(repo.get("updated_at")), source, repo_latency, repo_request,
              {"open_issues": repo.get("open_issues_count"), "updated_at": repo.get("updated_at")}),
        _case(repository, "popularity", isinstance(repo.get("stargazers_count"), int)
              and isinstance(repo.get("forks_count"), int), source, repo_latency, repo_request,
              {"stars": repo.get("stargazers_count"), "forks": repo.get("forks_count")}),
        _case(repository, "technology", bool(repo.get("language")), source, repo_latency, repo_request,
              {"language": repo.get("language"), "topics": repo.get("topics", [])}),
        _case(repository, "governance", isinstance(repo.get("archived"), bool)
              and isinstance(repo.get("disabled"), bool), source, repo_latency, repo_request,
              {"archived": repo.get("archived"), "disabled": repo.get("disabled"),
               "license": (repo.get("license") or {}).get("spdx_id")}),
    ]
    trajectory = {"session_id": f"github-{repository.replace('/', '-')}",
                  "query": f"Inspect the public repository {repository} using read-only tools.",
                  "model": "deterministic-github-agent-v2", "steps": [
                      {"step": index, "thought": f"Collect {case['task_family']} evidence.",
                       "action": {"name": f"github_{case['task_family']}",
                                  "arguments": json.dumps({"repository": repository})},
                       "observation": json.dumps(case["answer"], ensure_ascii=False)}
                      for index, case in enumerate(cases, 1)],
                  "final_answer": f"Completed {len(cases)} read-only tasks for {repository}."}
    return cases, trajectory, {"payload": repo, "latency_ms": repo_latency, "request_id": repo_request}


def _preflight(required_requests):
    payload, latency_ms, request_id = _get("/rate_limit")
    core = (payload.get("resources") or {}).get("core") or {}
    remaining = int(core.get("remaining", 0))
    return {"authenticated": bool(_github_token()), "limit": int(core.get("limit", 0)),
            "remaining": remaining, "reset": core.get("reset"),
            "required_requests": required_requests, "passed": remaining >= required_requests,
            "latency_ms": round(latency_ms, 3), "request_id": request_id}


def run_dataset(repositories=REPOSITORIES, cache_dir=None, preflight=True):
    cases, trajectories, failures = [], [], []
    cache_dir = Path(cache_dir) if cache_dir else None
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
    cached_count = sum(
        bool(cache_dir and (cache_dir / f"{repository.replace('/', '__')}.json").exists())
        for repository in repositories
    )
    quota = _preflight(len(repositories) - cached_count) if preflight else None
    if quota and not quota["passed"]:
        failures.append({"repository": "__preflight__", "error_type": "RateLimitBudget",
                         "error": f"need {quota['required_requests']} requests, {quota['remaining']} remain"})
        repositories = ()
    for repository in repositories:
        try:
            cache_path = cache_dir / f"{repository.replace('/', '__')}.json" if cache_dir else None
            cached = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path and cache_path.exists() else None
            repo_cases, trajectory, snapshot = _run_repository(repository, cached)
            if cache_path and not cached:
                cache_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            cases.extend(repo_cases)
            trajectories.append(trajectory)
        except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as exc:
            failures.append({"repository": repository, "error_type": type(exc).__name__,
                             "error": str(exc)})
    split_counts = {split: sum(case["split"] == split for case in cases) for split in SPLITS}
    failed_cases = [case for case in cases if not case["passed"]]
    manifest = [{"case_id": case["case_id"], "split": case["split"],
                 "source_url": case["source_url"]} for case in cases]
    fingerprint = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode("utf-8")).hexdigest()
    total = len(cases)
    traceable = bool(cases) and all(case.get("source_url") and case.get("request_id") for case in cases)
    return {"schema_version": "github-business-dataset/v2",
            "generated_at": datetime.now(timezone.utc).isoformat(), "system": "github-rest-api",
            "api_version": "2022-11-28", "agent_version": "deterministic-github-agent-v2",
            "read_only": True, "authenticated": bool(_github_token()), "rate_limit_preflight": quota,
            "dataset": {"repositories": list(repositories), "task_families": list(TASK_FAMILIES),
                        "split_policy": "repository-cluster isolation", "split_counts": split_counts,
                        "task_count": total, "fingerprint_sha256": fingerprint,
                        "source_license_boundary": "GitHub metadata; repository content keeps its source license."},
            "metrics": {"passed": sum(case["passed"] for case in cases), "total": total,
                        "task_success_rate": sum(case["passed"] for case in cases) / total if total else 0.0,
                        "human_handoff_rate": (len(failed_cases) + len(failures)) /
                                              (total + len(failures)) if total or failures else 0.0},
            "failure_slices": {"failed_cases": failed_cases, "repository_errors": failures},
            "human_review_queue": [case["case_id"] for case in failed_cases]
                                  + [f"github::{row['repository']}::collection" for row in failures],
            "cases": cases, "trajectories": trajectories,
            "completion_gate": {"minimum_tasks": 50, "has_held_out": split_counts["held_out"] > 0,
                                "source_traceability": traceable,
                                "passed": total >= 50 and split_counts["held_out"] > 0 and traceable},
            "evidence_boundary": "Real public API data and deterministic task execution; no production traffic or writes."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", action="append", dest="repositories")
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--skip-preflight", action="store_true")
    args = parser.parse_args()
    report = run_dataset(tuple(args.repositories) if args.repositories else REPOSITORIES,
                         cache_dir=args.cache_dir, preflight=not args.skip_preflight)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["completion_gate"]["passed"] and not report["failure_slices"]["repository_errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
