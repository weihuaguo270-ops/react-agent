"""Replayable triage execution records for failure diagnosis."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from .workflow import run_triage


def input_fingerprint(body: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def write_replay(path: str | Path, body: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Append a redacted, deterministic replay record as JSONL."""
    record = {
        "schema_version": "security-triage-replay/v1",
        "recorded_at": time.time(),
        "input_sha256": input_fingerprint(body),
        "input": body,
        "result": result,
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return record


def replay_record(record: dict[str, Any]) -> dict[str, Any]:
    if record.get("schema_version") != "security-triage-replay/v1":
        raise ValueError("unsupported replay schema")
    body = record.get("input")
    if not isinstance(body, dict):
        raise ValueError("replay input must be an object")
    return run_triage(body)


def load_replays(path: str | Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records
