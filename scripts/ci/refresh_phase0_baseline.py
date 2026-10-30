"""Refresh the CI Phase 0 baseline from GitHub's read-only APIs.

The output is intentionally a partial baseline: Phase 1 mapping and semantic
validation are not inferred from this snapshot.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

from audit_workflow_security import audit as audit_workflow_security

ROOT = Path(__file__).resolve().parents[2]
REPO = "weihuaguo270-ops/react-agent"
EVIDENCE = ROOT / "docs/specs/ci/evidence"


def gh_json(endpoint: str) -> object:
    result = subprocess.run(
        ["gh", "api", endpoint],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(result.stdout)


def iso_minutes(start: str, end: str) -> float:
    left = datetime.fromisoformat(start.replace("Z", "+00:00"))
    right = datetime.fromisoformat(end.replace("Z", "+00:00"))
    return round((right - left).total_seconds() / 60, 2)


def classify(job: str, step: str) -> tuple[str, str]:
    text = f"{job} {step}".lower()
    rules = (
        ("dependency_or_environment", ("install", "setup", "pip", "clone")),
        ("security_audit", ("security", "audit", "pip-audit")),
        ("docker_runtime_or_healthcheck", ("docker", "container", "health")),
        ("pr_readiness_gate", ("readiness", "pr ready")),
        ("live_provider_or_network", ("real llm", "deepseek", "provider")),
        ("lint", ("lint", "ruff")),
        ("typecheck", ("typecheck", "mypy")),
        ("daily_smoke_and_variance", ("daily smoke", "variance log")),
        ("test_or_evaluation", ("pytest", "test", "evaluation")),
    )
    for category, needles in rules:
        if any(needle in text for needle in needles):
            return category, "job/step name heuristic; inspect logs for root cause"
    return "unclassified", "job/step name did not support a narrower category"


def reproduction_command(job: str, step: str) -> str | None:
    text = f"{job} {step}".lower()
    if "readiness" in text:
        return "python scripts/ci/check_pr_ready.py --ci --base-sha <PR_BASE_SHA> --allow-revert"
    if "pytest (offline)" in text:
        return "pytest tests/ -q --ignore=tests/test_real_llm.py"
    if "coverage" in text:
        return "pytest tests/ -q --ignore=tests/test_real_llm.py --cov=react_agent --cov-fail-under=35"
    if "harness p4" in text:
        return "python scripts/ci/harness_stage_gate.py --stage P4"
    if "docs troubleshoot golden" in text:
        return "python scripts/eval/docs/run_docs_troubleshoot_eval.py"
    if "pillar ① execution" in text:
        return "REACT_AGENT_SKIP_RAG=1 python scripts/eval/execution/run_execution_suite.py"
    if "daily smoke" in text:
        return "python scripts/eval/smoke/run_daily_smoke.py"
    if "commit variance log" in text:
        return "gh workflow run daily-smoke.yml"
    if "lint" in text or "ruff" in text:
        return "ruff check src/ tests/"
    if "typecheck" in text or "mypy" in text:
        return "mypy src/react_agent --ignore-missing-imports"
    if "pip-audit" in text or "security" in text:
        return "pip-audit --progress-spinner off"
    if "docker" in text or "container" in text:
        return "docker build -t react-agent:ci . && python scripts/eval/smoke/run_deploy_smoke.py"
    if "real llm" in text or "deepseek" in text:
        return "pytest tests/test_real_llm.py -v -m real_llm_smoke"
    if "install" in text or "setup" in text:
        return "pip install -e \".[test]\""
    return None


def reviewed_jobs(run: dict) -> list[dict]:
    if run.get("conclusion") not in {"failure", "cancelled", "timed_out", "action_required"}:
        return []
    payload = gh_json(f"repos/{REPO}/actions/runs/{run['id']}/jobs?per_page=100")
    output = []
    for job in payload.get("jobs", []):
        if job.get("conclusion") not in {"failure", "cancelled", "timed_out", "action_required"}:
            continue
        failed_steps = []
        for step in job.get("steps", []):
            if step.get("conclusion") not in {"failure", "cancelled", "timed_out", "action_required"}:
                continue
            category, basis = classify(job.get("name", ""), step.get("name", ""))
            failed_steps.append(
                {
                    "name": step.get("name"),
                    "conclusion": step.get("conclusion"),
                    "category": category,
                    "classification_basis": basis,
                    "reproduction_command": reproduction_command(job.get("name", ""), step.get("name", "")),
                }
            )
        output.append(
            {
                "name": job.get("name"),
                "conclusion": job.get("conclusion"),
                "failed_steps": failed_steps,
            }
        )
    return output


def association(run: dict, prs_by_sha: dict[str, list[int]]) -> tuple[list[int], list[str]]:
    numbers = [item["number"] for item in run.get("pull_requests", [])]
    basis = ["actions_api_pull_requests"] if numbers else []
    if not numbers and run.get("head_sha") in prs_by_sha:
        numbers = prs_by_sha[run["head_sha"]]
        basis = ["exact_pr_head_sha"]
    return numbers, basis


def collect_runs(workflow: str, limit: int, prs_by_sha: dict[str, list[int]]) -> list[dict]:
    payload = gh_json(f"repos/{REPO}/actions/workflows/{workflow}/runs?per_page={limit}")
    output = []
    for run in payload.get("workflow_runs", []):
        output.append(run_record(run, workflow, prs_by_sha))
    return output


def run_record(run: dict, workflow: str, prs_by_sha: dict[str, list[int]] | None = None) -> dict:
    numbers, basis = association(run, prs_by_sha or {})
    return {
            "run_id": run["id"],
            "url": run["html_url"],
            "workflow": workflow,
            "run_number": run.get("run_number"),
            "run_attempt": run.get("run_attempt"),
            "display_title": run.get("display_title"),
            "event": run.get("event"),
            "conclusion": run.get("conclusion"),
            "head_branch": run.get("head_branch"),
            "head_sha": run.get("head_sha"),
            "created_at": run.get("created_at"),
            "updated_at": run.get("updated_at"),
            "wall_clock_minutes": iso_minutes(run["created_at"], run["updated_at"]),
            "pull_request_numbers": numbers,
            "association_basis": basis,
            "reviewed_jobs": reviewed_jobs(run),
            "classification_basis": "run conclusion and Jobs API failed steps; association uses recorded API links or exact head SHA",
            "run_mode": "offline_mock_plus_optional_write_automation"
            if workflow == "daily-smoke.yml"
            else "offline_ci_with_conditional_live_llm",
        }


def collect_merge_followups(prs: list[dict]) -> list[dict]:
    """Collect all workflow runs attached to the merge commits for PR 172/173."""
    output = []
    seen: set[int] = set()
    for pr in prs:
        if pr.get("number") not in {172, 173} or not pr.get("merge_commit_sha"):
            continue
        payload = gh_json(f"repos/{REPO}/actions/runs?head_sha={pr['merge_commit_sha']}&per_page=100")
        for run in payload.get("workflow_runs", []):
            if run["id"] in seen:
                continue
            seen.add(run["id"])
            item = run_record(run, run.get("path", "").rsplit("/", 1)[-1] or run.get("name", "unknown"))
            item["merge_pr_number"] = pr["number"]
            item["association_basis"] = ["merge_commit_sha"]
            output.append(item)
    return output


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    index = min(len(values) - 1, round((len(values) - 1) * fraction))
    return round(values[index], 2)


def summarize(runs: list[dict]) -> dict:
    by_conclusion = {}
    for run in runs:
        by_conclusion[run["conclusion"]] = by_conclusion.get(run["conclusion"], 0) + 1
    durations = [run["wall_clock_minutes"] for run in runs]
    return {
        "count": len(runs),
        "by_conclusion": by_conclusion,
        "wall_clock_minutes": {
            "p50": round(median(durations), 2) if durations else None,
            "p95": percentile(durations, 0.95),
            "max": max(durations) if durations else None,
        },
    }


def workflow_responsibilities() -> list[dict]:
    """Freeze the current workflow-to-logical-group mapping before Registry v2."""
    return [
        {
            "workflow": "test.yml",
            "job": "pr-ready",
            "logical_group": "pr_readiness",
            "mode": "pull_request_only",
            "target_phase": "Phase 2",
            "required_now": True,
        },
        {
            "workflow": "test.yml",
            "job": "lint",
            "logical_group": "lint",
            "mode": "offline",
            "target_phase": "Phase 2-3",
            "required_now": True,
        },
        {
            "workflow": "test.yml",
            "job": "test",
            "logical_group": "python_matrix_and_full_offline_evaluation",
            "mode": "offline_plus_sibling_repositories",
            "target_phase": "Phase 2",
            "required_now": True,
        },
        {
            "workflow": "test.yml",
            "job": "test-windows",
            "logical_group": "windows_matrix_and_console_guards",
            "mode": "offline",
            "target_phase": "Phase 2",
            "required_now": True,
        },
        {
            "workflow": "test.yml",
            "job": "typecheck",
            "logical_group": "typecheck",
            "mode": "static",
            "target_phase": "Phase 2-3",
            "required_now": True,
        },
        {
            "workflow": "test.yml",
            "job": "security",
            "logical_group": "dependency_security",
            "mode": "offline_dependency_audit",
            "target_phase": "Phase 2-3",
            "required_now": True,
        },
        {
            "workflow": "test.yml",
            "job": "docker-smoke",
            "logical_group": "docker_runtime_smoke",
            "mode": "docker",
            "target_phase": "Phase 2-3",
            "required_now": True,
        },
        {
            "workflow": "daily-smoke.yml",
            "job": "daily-smoke",
            "logical_group": "daily_smoke_evidence",
            "mode": "offline_mock_evidence_only",
            "target_phase": "Phase 0",
            "required_now": False,
        },
        {
            "workflow": "harness.yml",
            "job": "Harness P4 stage gate",
            "logical_group": "stage_gate",
            "mode": "harness_stage_gate",
            "target_phase": "direction_spec",
            "required_now": True,
        },
        {
            "workflow": "evaluation.yml",
            "job": "Evaluation evidence",
            "logical_group": "evaluation_evidence",
            "mode": "evidence_only",
            "target_phase": "Phase 0",
            "required_now": False,
        },
    ]


def reproduction_metadata() -> dict:
    return {
        "source_of_truth": "workflow run URL, run_id, head_sha, reviewed job/step and command fields in this report",
        "commands": {
            "pr_readiness": "python scripts/ci/check_pr_ready.py --ci --base-sha <PR_BASE_SHA> --allow-revert",
            "offline_tests": "pytest tests/ -q --ignore=tests/test_real_llm.py",
            "lint": "ruff check src/ tests/",
            "typecheck": "mypy src/react_agent --ignore-missing-imports",
            "security": "pip-audit --progress-spinner off",
            "docker_smoke": "docker build -t react-agent:ci . && python scripts/eval/smoke/run_deploy_smoke.py",
            "real_llm": "pytest tests/test_real_llm.py -v -m real_llm_smoke",
        },
        "classification_boundary": "job/step names classify likely category; root cause requires the linked GitHub log",
    }


def limitations() -> list[str]:
    return [
        "Wall-clock is created_at to updated_at and includes queue time; it is not execution-only duration.",
        "GitHub API sample is the latest 100 PRs, 100 test.yml runs, and 50 daily-smoke.yml runs; no historical pagination beyond those limits.",
        "Failure categories are name-based triage hints and do not replace log-level root-cause review.",
        "The current spec-registry/v1 has no path rules, so mapping coverage is intentionally not_measured.",
        "The R9 snapshot is static evidence; fork Secret isolation and runtime permission behavior require a Phase 1 acceptance run.",
        "The Phase 1 matrix is frozen as a contract for later work and is not evidence that Phase 1 has passed.",
    ]


def phase1_matrix_review() -> dict:
    return {
        "status": "frozen_contract_reviewed",
        "source": "docs/specs/ci/redesign-plan.md#phase-1-registry-and-stage-signals",
        "scenario_count": 13,
        "execution_status": "not_executed_in_phase_0",
        "reason": "Phase 0 freezes the acceptance contract; semantic validator, backtest, progress comparator and R9 tests belong to Phase 1.",
    }


def render_markdown(report: dict) -> str:
    test = report["workflows"]["test.yml"]
    daily = report["workflows"]["daily-smoke.yml"]
    checks = report["required_checks"]
    return f"""# CI Phase 0 基线报告

## 状态

**阶段状态：** Partial（基线快照和安全快照已刷新；独立复审、Registry v2 语义校验和 R9 验收仍未完成）<br>
**采集时间：** {report['collected_at']}<br>
**仓库：** {REPO}
**默认分支 SHA：** `{report['default_branch']['sha']}`<br>
**来源：** GitHub Actions、Pull Request、Branch Protection 只读 API 快照。

本报告只冻结当前事实，不把 Registry v2、路径映射、聚合器或 Branch Protection 迁移解释为已完成。

## 样本与方法

- PR 样本：{report['pull_requests']['sample_size']} 条，范围 `{report['pull_requests']['from_created_at']}` 至 `{report['pull_requests']['to_created_at']}`。
- `test.yml`：{test['count']} 次，结论统计 `{json.dumps(test['by_conclusion'], ensure_ascii=False)}`。
- `daily-smoke.yml`：{daily['count']} 次，结论统计 `{json.dumps(daily['by_conclusion'], ensure_ascii=False)}`。
- 每个失败、取消、超时或 action-required run 都通过 Jobs API 展开到失败 job/step；分类仅作定位提示，不能替代日志根因。

## Workflow 职责映射

| Workflow | Job | 逻辑测试组 | 运行模式 | 目标阶段 | 当前 required |
|---|---|---|---|---|---:|
{chr(10).join(f"| `{item['workflow']}` | `{item['job']}` | `{item['logical_group']}` | `{item['mode']}` | `{item['target_phase']}` | {'yes' if item['required_now'] else 'no'} |" for item in report['workflow_responsibilities'])}

该表是 Registry v2 之前的初步迁移表；它不表示路径映射已经实现。

## 当前 Required Checks

{chr(10).join(f'- `{item}`' for item in checks)}

Branch Protection：strict={report['branch_protection']['strict']}，管理员保护={report['branch_protection']['enforce_admins']}，线性历史={report['branch_protection']['required_linear_history']}，稳定聚合器={report['branch_protection']['stable_required_aggregator_present']}。

当前仍没有稳定聚合器；`Real LLM gate` 只表示 Secret 探测，不等价于实际 smoke 通过。

## PR #172/#173 合并后 push runs

{chr(10).join(f"- PR #{run['merge_pr_number']}：run `{run['run_id']}`，workflow `{run['workflow']}`，event `{run['event']}`，conclusion `{run['conclusion']}`，head `{run['head_sha']}`" for run in report['merge_followup_runs']) or '- 未发现对应的合并提交 workflow run；需在复审时核对 API 返回。'}

## 时长快照

| Workflow | N | P50 | P95 | 最大 |
|---|---:|---:|---:|---:|
| `test.yml` | {test['wall_clock_minutes']['count'] if 'count' in test['wall_clock_minutes'] else test['count']} | {test['wall_clock_minutes']['p50']} | {test['wall_clock_minutes']['p95']} | {test['wall_clock_minutes']['max']} |
| `daily-smoke.yml` | {daily['wall_clock_minutes']['count'] if 'count' in daily['wall_clock_minutes'] else daily['count']} | {daily['wall_clock_minutes']['p50']} | {daily['wall_clock_minutes']['p95']} | {daily['wall_clock_minutes']['max']} |

这些是从创建到更新时间的墙钟近似值，包含排队，不能直接作为 PR gate 执行时长目标。

## Phase 0 退出结论

仍待完成：独立复审逐样本证据、Phase 1 语义校验和 R9 正式验收。Phase 1 验收矩阵已冻结并复核为后续契约，但没有在本阶段执行。当前 v1 Registry 没有 path rules，因此 mapping coverage 保持 `not_measured`，不得伪造历史覆盖率。

## 复核边界

- 复现命令：见 JSON 的 `reproduction`。
- 限制：见 JSON 的 `limitations`。
- R9 静态安全快照：见 `phase0-r9-security-snapshot.md`；其中的 finding 是待整改项，不是通过结论。
"""


def render_index(report: dict) -> str:
    rows = [
        "# Phase 0 样本索引",
        "",
        "JSON 是权威机器可读记录；本文件只用于逐条浏览。",
        "",
        "## 最近 100 个 PR",
        "",
        "| PR | 创建时间 UTC | 状态 | 合并 | base SHA | head SHA | 合并提交 | test run IDs | daily-smoke run IDs |",
        "|---:|---|---|---|---|---|---|---|---|",
    ]
    for pr in report["pull_requests"]["samples"]:
        rows.append(
            f"| [#{pr['number']}]({pr['url']}) | {pr['created_at']} | {pr['state']} | "
            f"{'yes' if pr['merged'] else 'no'} | `{pr['base_sha']}` | `{pr['head_sha']}` | "
            f"`{pr.get('merge_commit_sha') or '—'}` | "
            f"{', '.join(str(run_id) for run_id in pr['test_run_ids']) or '—'} | "
            f"{', '.join(str(run_id) for run_id in pr['daily_run_ids']) or '—'} |"
        )
    rows.extend([
        "",
        "## test.yml 与 daily-smoke.yml runs",
        "",
        "| run | workflow | event | conclusion | head SHA | PR | failed jobs |",
        "|---:|---|---|---|---|---|---|",
    ])
    for workflow in ("test.yml", "daily-smoke.yml"):
        for run in report["workflows"][workflow]["runs"]:
            jobs = ", ".join(job["name"] for job in run["reviewed_jobs"]) or "-"
            prs = ", ".join(f"#{number}" for number in run["pull_request_numbers"]) or "-"
            rows.append(
                f"| [{run['run_id']}]({run['url']}) | {workflow} | {run['event']} | {run['conclusion']} | `{run['head_sha']}` | {prs} | {jobs} |"
            )
    return "\n".join(rows) + "\n"


def main() -> int:
    global REPO
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=REPO)
    args = parser.parse_args()
    REPO = args.repo

    prs_payload = gh_json(f"repos/{REPO}/pulls?state=all&sort=created&direction=desc&per_page=100")
    prs = prs_payload if isinstance(prs_payload, list) else prs_payload.get("pulls", [])
    prs_by_sha: dict[str, list[int]] = {}
    for pr in prs:
        prs_by_sha.setdefault(pr["head"]["sha"], []).append(pr["number"])
    test_runs = collect_runs("test.yml", 100, prs_by_sha)
    daily_runs = collect_runs("daily-smoke.yml", 50, prs_by_sha)
    protection = gh_json(f"repos/{REPO}/branches/main/protection")
    default_branch = gh_json(f"repos/{REPO}")["default_branch"]
    default_sha = gh_json(f"repos/{REPO}/git/ref/heads/{default_branch}")["object"]["sha"]
    current_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()
    runs_by_sha: dict[str, list[dict]] = {}
    for run in test_runs + daily_runs:
        runs_by_sha.setdefault(run["head_sha"], []).append(run)
    pr_samples = []
    for pr in prs:
        linked = runs_by_sha.get(pr["head"]["sha"], [])
        pr_samples.append(
            {
                "number": pr["number"],
                "url": pr["html_url"],
                "state": pr["state"],
                "merged": bool(pr.get("merged_at")),
                "created_at": pr.get("created_at"),
                "updated_at": pr.get("updated_at"),
                "merged_at": pr.get("merged_at"),
                "merge_commit_sha": pr.get("merge_commit_sha"),
                "base_sha": pr["base"]["sha"],
                "head_sha": pr["head"]["sha"],
                "head_ref": pr["head"]["ref"],
                "base_ref": pr["base"]["ref"],
                "test_run_ids": [run["run_id"] for run in linked if run["workflow"] == "test.yml"],
                "daily_run_ids": [run["run_id"] for run in linked if run["workflow"] == "daily-smoke.yml"],
            }
        )
    report = {
        "schema_version": "ci-baseline/v2",
        "status": "partial",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "repository": REPO,
        "default_branch": {"name": default_branch, "sha": default_sha},
        "sample_definition": {
            "pull_requests": "latest 100 returned by GitHub REST pulls endpoint sorted by created desc",
            "test_workflow_runs": "latest 100 returned by test.yml workflow runs endpoint",
            "daily_workflow_runs": "latest 50 returned by daily-smoke.yml workflow runs endpoint",
            "failure_job_details": "all failure/cancelled/timed_out/action_required runs expanded through the jobs API",
        },
        "pull_requests": {
            "sample_size": len(prs),
            "from_created_at": prs[-1].get("created_at") if prs else None,
            "to_created_at": prs[0].get("created_at") if prs else None,
            "samples": pr_samples,
        },
        "workflows": {
            "test.yml": {**summarize(test_runs), "runs": test_runs},
            "daily-smoke.yml": {**summarize(daily_runs), "runs": daily_runs},
        },
        "merge_followup_runs": collect_merge_followups(prs),
        "workflow_responsibilities": workflow_responsibilities(),
        "reproduction": reproduction_metadata(),
        "limitations": limitations(),
        "audit_fields": {
            "run_identity": ["run_id", "url", "workflow", "event", "head_sha"],
            "association": ["pull_request_numbers", "association_basis"],
            "failure_review": ["reviewed_jobs", "failed_steps", "category", "classification_basis", "reproduction_command"],
            "timing": ["created_at", "updated_at", "wall_clock_minutes"],
            "conclusion_boundary": ["run_mode", "mapping_coverage_backtest", "fresh_rerun_required_for_completion"],
        },
        "phase1_acceptance_matrix_review": phase1_matrix_review(),
        "r9_security_snapshot": audit_workflow_security(),
        "required_checks": protection.get("required_status_checks", {}).get("contexts", []),
        "branch_protection": {
            "strict": protection.get("required_status_checks", {}).get("strict"),
            "enforce_admins": protection.get("enforce_admins", {}).get("enabled"),
            "required_linear_history": protection.get("required_linear_history", {}).get("enabled"),
            "stable_required_aggregator_present": False,
        },
        "owners": {"ci_maintainer": "repository_maintainers", "registry_maintainer": "repository_maintainers", "progress_owner": "repository_maintainers", "branch_protection_operator": "repository_maintainers"},
        "comparison_scope": {"baseline_ref": default_branch, "baseline_sha": default_sha, "current_worktree_ref": subprocess.run(["git", "branch", "--show-current"], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip(), "current_worktree_sha": current_sha, "fresh_rerun_required_for_completion": True},
        "mapping_coverage_backtest": {"status": "not_measured", "reason": "spec-registry/v1 has no path rules", "planned_phase": "Phase 1", "required_before": "Phase 2", "required_outputs": ["mapped_coverage", "unmapped_paths", "false_positive_rules", "missed_expected_rules"]},
    }
    historical_log_review = EVIDENCE / "phase0-failure-log-review-2026-10-28.json"
    if historical_log_review.exists():
        review = json.loads(historical_log_review.read_text(encoding="utf-8"))
        summary = review.get("summary", {})
        sample = review.get("sample", {})
        report["historical_failure_log_review"] = {
            "path": historical_log_review.name,
            "sample_sha": sample.get("baseline_sha"),
            "failure_jobs": summary.get("failure_jobs"),
            "confirmed_root_causes": summary.get("confirmed_root_causes"),
            "partial_root_causes": summary.get("partial_root_causes"),
            "unavailable_logs": summary.get("unavailable_logs"),
            "status_note": "Historical log review is retained separately and is not treated as fresh evidence for the current main SHA.",
        }
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    r9_report = report["r9_security_snapshot"]
    (EVIDENCE / "phase0-baseline.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (EVIDENCE / "phase0-baseline.md").write_text(render_markdown(report), encoding="utf-8")
    (EVIDENCE / "phase0-sample-index.md").write_text(render_index(report), encoding="utf-8")
    (EVIDENCE / "phase0-r9-security-snapshot.json").write_text(
        json.dumps(r9_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    from audit_workflow_security import render as render_security_audit

    (EVIDENCE / "phase0-r9-security-snapshot.md").write_text(
        render_security_audit(r9_report), encoding="utf-8"
    )
    print(f"baseline={EVIDENCE / 'phase0-baseline.json'}")
    print(f"default_sha={default_sha}")
    print(f"pr_samples={len(prs)} test_runs={len(test_runs)} daily_runs={len(daily_runs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
