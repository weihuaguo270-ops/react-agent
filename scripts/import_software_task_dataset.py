"""导入人工审核后的公开历史软件任务记录。"""
from __future__ import annotations

import argparse

from react_agent.eval.software_task_dataset import import_software_task_records


def main() -> None:
    parser = argparse.ArgumentParser(description="Import reviewed software task records")
    parser.add_argument("records", help="JSON array or JSONL records exported from a public source")
    parser.add_argument("output", help="destination dataset manifest JSON")
    parser.add_argument("--dataset-id", default="public-history-software-tasks")
    parser.add_argument("--version", default="0.1.0")
    args = parser.parse_args()
    dataset = import_software_task_records(
        args.records,
        args.output,
        dataset_id=args.dataset_id,
        version=args.version,
    )
    print(f"imported {len(dataset.tasks)} tasks: {dataset.content_hash()}")


if __name__ == "__main__":
    main()
