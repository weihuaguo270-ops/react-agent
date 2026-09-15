"""运行一条 manifest 软件任务的真实修复闭环。"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from react_agent.apps.react_patch_planner import ReActPatchPlanner, configured_model_call
from react_agent.eval.repair_loop import RepairLoop
from react_agent.eval.repair_executor import DockerTaskExecutor
from react_agent.eval.task_manifest import build_runner, load_tasks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("--repository", required=True, help="本地 FastAPI 仓库路径")
    parser.add_argument("--manifest", default="react-agent/eval/software_task_dataset_manifest.json")
    args = parser.parse_args()
    task = next((x for x in load_tasks(args.manifest) if x.get("task_id") == args.task_id), None)
    if task is None:
        raise SystemExit(f"task not found: {args.task_id}")
    hidden_asset = task.get("hidden_test_asset")
    if not hidden_asset:
        raise SystemExit("task has no hidden_test_asset")
    manifest_path = Path(args.manifest).resolve()
    software_task, runner = build_runner(task, args.repository, artifact_root=manifest_path.parent.parent / "artifacts" / "software-tasks")
    ready, error = runner.verify_runtime()
    if not ready:
        raise SystemExit(error or "Docker runtime is unavailable")
    from react_agent.llm import LLM
    planner = ReActPatchPlanner(configured_model_call(LLM()))
    source = {}
    for path in task["allowed_paths"]:
        result = subprocess.run(["git", "show", f"{task['base_commit']}:{path}"], cwd=args.repository,
                                capture_output=True, text=True, encoding="utf-8")
        if result.returncode != 0:
            raise SystemExit(f"cannot read baseline source {path}: {result.stderr.strip()}")
        source[path] = result.stdout
    context = {"task": task.get("acceptance_criteria", []), "issue": task.get("issue_url", ""),
               "source": source, "allowed_paths": task["allowed_paths"]}
    executor = DockerTaskExecutor(software_task, runner)
    try:
        # First evaluate the unrepaired baseline outcome through the gate when
        # siblings are present; RepairLoop then feeds forced reverify.
        from react_agent.eval.failure_regression_gate import (
            attach_software_task_gate,
            siblings_available,
        )

        def repair_fn(_hold_report):
            return RepairLoop(
                planner=planner,
                executor=executor,
                allowed_paths=tuple(task["allowed_paths"]),
            ).run(context)

        if siblings_available()[0]:
            # Seed a failing task envelope so the initial gate holds, then repair.
            seed = {
                "task_id": task["task_id"],
                "task_hash": software_task.content_hash(),
                "status": "failed",
                "unauthorized_paths": [],
                "public_test": {"status": "failed"},
                "hidden_test": {},
            }
            result = attach_software_task_gate(
                seed,
                out_dir=Path(runner.config.artifact_dir) / "runs" / f"{args.task_id}-repair-gate",
                task_id=args.task_id,
                repair_fn=repair_fn,
                rebuild_task_result_fn=lambda repair: {
                    "task_id": task["task_id"],
                    "task_hash": software_task.content_hash(),
                    "status": "succeeded" if repair.get("status") == "succeeded" else "failed",
                    "unauthorized_paths": [],
                    "public_test": {"status": "passed" if repair.get("status") == "succeeded" else "failed"},
                    "hidden_test": {"status": "passed" if repair.get("status") == "succeeded" else "failed"},
                },
            )
        else:
            result = repair_fn({})
    finally:
        executor.close()
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
