"""从企业系统只读采集任务并输出脱敏后的统一数据集。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from react_agent.eval.business_pilot import redact_payload  # noqa: E402
from react_agent.eval.connectors import (  # noqa: E402
    ConnectorConfig,
    GitLabAdapter,
    JiraAdapter,
    ReadOnlyHttpClient,
    ServiceNowAdapter,
    TraceAdapter,
    ZendeskAdapter,
    load_env_file,
)


def _build_adapter(args):
    prefix = args.source.upper()
    client = ReadOnlyHttpClient(ConnectorConfig.from_env(prefix))
    if args.source == "jira":
        return JiraAdapter(client, jql=args.query, max_items=args.limit)
    if args.source == "gitlab":
        if not args.project_id:
            raise ValueError("--project-id is required for GitLab")
        return GitLabAdapter(client, args.project_id, max_items=args.limit)
    if args.source == "zendesk":
        return ZendeskAdapter(client, max_items=args.limit)
    if args.source == "servicenow":
        return ServiceNowAdapter(client, table=args.table, max_items=args.limit)
    if not args.trace_id:
        raise ValueError("at least one --trace-id is required for APM")
    return TraceAdapter(
        client,
        args.query_path,
        trace_ids=args.trace_id,
        max_items=args.limit,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, choices=("jira", "gitlab", "zendesk", "servicenow", "apm"))
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--query", default="order by updated DESC")
    parser.add_argument("--project-id")
    parser.add_argument("--table", default="incident")
    parser.add_argument("--query-path", default="/traces")
    parser.add_argument("--trace-id", action="append", default=[])
    args = parser.parse_args()
    load_env_file(ROOT / ".env")
    if args.limit < 1 or args.limit > 1000:
        parser.error("--limit must be between 1 and 1000")

    try:
        adapter = _build_adapter(args)
        tasks = adapter.fetch()
    except ValueError as exc:
        parser.error(str(exc))

    # 连接器只完成基础凭据/个人信息遮蔽；上线前仍需业务方执行字段级复核。
    scrubbed = redact_payload(tasks)
    for task in scrubbed:
        task["redaction"] = {
            "applied": True,
            "version": "builtin-basic-v1",
            "human_verified": False,
        }
    rendered_tasks = json.dumps(scrubbed, ensure_ascii=False, sort_keys=True)
    dataset = {
        "schema_version": "business-pilot/v1",
        "project": f"{args.source}-readonly-import",
        "evidence_level": "enterprise_read_only",
        "source": args.source,
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
        "data_sha256": hashlib.sha256(rendered_tasks.encode("utf-8")).hexdigest(),
        "requests": adapter.client.audit,
        "tasks": scrubbed,
        "boundary": (
            "Read-only import with basic redaction. Agent runs, human review and final "
            "business-state verification are not populated by this collector."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(dataset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"source": args.source, "tasks": len(scrubbed), "out": str(args.out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
