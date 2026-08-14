"""运行 GitHub 工程任务的影子验证或受控候选交付。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from react_agent.apps.github_delivery import (
    Approval,
    DeliveryTask,
    GitHubDeliveryWorkflow,
    WorkflowConfig,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", type=Path)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=("shadow", "guarded"), default="shadow")
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--episode-out", type=Path)
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument("--publish-draft-pr", action="store_true")
    args = parser.parse_args()

    task = DeliveryTask.from_dict(json.loads(args.task.read_text(encoding="utf-8")))
    approval = None
    if args.approval:
        approval = Approval.from_dict(json.loads(args.approval.read_text(encoding="utf-8")))
    workflow = GitHubDeliveryWorkflow(WorkflowConfig(
        artifact_dir=args.artifact_dir,
        mode=args.mode,
        publish_draft_pr=args.publish_draft_pr,
    ))
    report = workflow.run(task, approval=approval, idempotency_key=args.idempotency_key)
    if args.episode_out:
        args.episode_out.parent.mkdir(parents=True, exist_ok=True)
        args.episode_out.write_text(
            json.dumps(report["episode"], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
