"""GitHub REST backend for the remote delivery MCP service."""
from __future__ import annotations

import json
import os
from urllib import error, parse, request


class GitHubRESTBackend:
    """Small dependency-free GitHub API adapter.

    The remote worker owns the token.  The caller must still provide the MCP
    server's approval fields for write operations; this class is not a policy
    bypass.  ``create_draft_pr`` assumes the head branch already exists on the
    remote repository, which keeps branch creation/push in the controlled
    worker or CI pipeline rather than embedding git credentials in the Agent.
    """

    def __init__(self, token: str, *, api_base_url: str = "https://api.github.com", timeout: float = 20):
        if not token:
            raise ValueError("GitHub token is required")
        self.token = token
        self.api_base_url = api_base_url.rstrip("/")
        self.timeout = float(timeout)

    @classmethod
    def from_env(cls, *, token_env: str = "GITHUB_TOKEN", **kwargs):
        return cls(os.environ.get(token_env, ""), **kwargs)

    def create_draft_pr(self, arguments):
        owner, repo = _repo_parts(arguments["repository"])
        branch = str(arguments["branch"])
        payload = {
            "title": f"Agent: resolve {arguments['task_id']}",
            "body": (
                f"Source task: {arguments.get('issue_url', '')}\n\n"
                f"Plan: `{arguments['plan_sha256']}`\n\n"
                "Created by the controlled react-agent delivery worker."
            ),
            "head": branch,
            "base": arguments["base_branch"],
            "draft": True,
        }
        response = self._request("POST", f"/repos/{owner}/{repo}/pulls", payload)
        return {
            "url": response.get("html_url", ""),
            "number": response.get("number"),
            "status": "draft",
            "repository": f"{owner}/{repo}",
            "branch": branch,
        }

    def get_ci_status(self, arguments):
        owner, repo = _repo_parts(arguments["repository"])
        ref = parse.quote(str(arguments["ref"]), safe="")
        response = self._request("GET", f"/repos/{owner}/{repo}/commits/{ref}/check-runs")
        runs = response.get("check_runs") if isinstance(response, dict) else []
        runs = runs if isinstance(runs, list) else []
        return {
            "repository": f"{owner}/{repo}",
            "ref": arguments["ref"],
            "status": _aggregate_status(runs),
            "check_runs": [
                {
                    "name": item.get("name", ""),
                    "status": item.get("status", ""),
                    "conclusion": item.get("conclusion"),
                    "url": item.get("html_url", ""),
                }
                for item in runs
            ],
        }

    def trigger_ci(self, arguments):
        owner, repo = _repo_parts(arguments["repository"])
        workflow = str(arguments.get("workflow") or "").strip()
        if not workflow:
            raise ValueError("workflow is required to trigger CI")
        self._request(
            "POST",
            f"/repos/{owner}/{repo}/actions/workflows/{parse.quote(workflow, safe='')}/dispatches",
            {"ref": arguments["ref"], "inputs": arguments.get("inputs", {})},
        )
        return {
            "repository": f"{owner}/{repo}",
            "ref": arguments["ref"],
            "workflow": workflow,
            "status": "queued",
        }

    def _request(self, method: str, path: str, payload=None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = request.Request(
            f"{self.api_base_url}{path}",
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
                "User-Agent": "react-agent-delivery-worker",
            },
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else {}
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"GitHub API {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"GitHub API connection failed: {exc.reason}") from exc


def _repo_parts(value: str) -> tuple[str, str]:
    parsed = parse.urlparse(str(value))
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"github.com", "www.github.com"}:
        raise ValueError("repository must be an https://github.com/<owner>/<repo> URL")
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) != 2:
        raise ValueError("repository must include owner and repo")
    return parts[0], parts[1].removesuffix(".git")


def _aggregate_status(runs: list[dict]) -> str:
    if not runs:
        return "unknown"
    if any(item.get("status") != "completed" for item in runs):
        return "pending"
    if any(item.get("conclusion") not in {"success", "neutral", "skipped"} for item in runs):
        return "failure"
    return "success"


__all__ = ["GitHubRESTBackend"]
