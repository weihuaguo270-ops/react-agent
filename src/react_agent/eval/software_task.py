"""Frozen software-engineering task contract independent of service dependencies."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping


SCHEMA_VERSION = "software-task/v1"
_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SPLITS = frozenset({"dev", "golden", "held_out"})


def _non_empty(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} must not be empty")
    return text


def _command(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError(f"{field} must be a non-empty command array")
    result = tuple(_non_empty(item, f"{field}[]") for item in value)
    if len(result) > 32:
        raise ValueError(f"{field} is too long")
    return result


def _strings(value: Any, field: str, *, required: bool = True) -> tuple[str, ...]:
    if value is None and not required:
        return ()
    if not isinstance(value, (list, tuple)) or (required and not value):
        raise ValueError(f"{field} must be a non-empty string array")
    result = tuple(_non_empty(item, f"{field}[]") for item in value)
    if len(result) > 128:
        raise ValueError(f"{field} has too many entries")
    return result


@dataclass(frozen=True)
class SoftwareTask:
    """A reproducible software task and its acceptance boundary.

    A mandatory base commit makes a task comparable across Agent versions.
    Hidden tests are optional for public-only smoke tasks, but reserved in the
    contract so later runners do not need another task format.
    """

    task_id: str
    repository: str
    issue_url: str
    base_commit: str
    split: str
    test_command: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    allowed_paths: tuple[str, ...]
    hidden_test_command: tuple[str, ...] = ()
    hidden_test_asset: str | None = None
    timeout_seconds: int = 600
    max_output_bytes: int = 2_000_000
    remote_repository: str | None = None
    idempotency_key: str | None = None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        task_id = _non_empty(self.task_id, "task_id")
        if not _TASK_ID.fullmatch(task_id):
            raise ValueError("task_id must match [A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version: {self.schema_version}")
        _non_empty(self.repository, "repository")
        _non_empty(self.issue_url, "issue_url")
        _non_empty(self.base_commit, "base_commit")
        if self.split not in _SPLITS:
            raise ValueError("split must be one of dev, golden, held_out")
        _command(self.test_command, "test_command")
        _strings(self.acceptance_criteria, "acceptance_criteria")
        _strings(self.allowed_paths, "allowed_paths")
        if self.hidden_test_command:
            _command(self.hidden_test_command, "hidden_test_command")
        if self.hidden_test_asset is not None:
            asset = _non_empty(self.hidden_test_asset, "hidden_test_asset")
            normalized = asset.replace("\\", "/")
            if normalized.startswith("/") or ":" in normalized or any(
                part in {"", ".", ".."} for part in normalized.split("/")
            ):
                raise ValueError("hidden_test_asset must be a safe relative path")
            if not self.hidden_test_command:
                raise ValueError("hidden_test_asset requires hidden_test_command")
        if not isinstance(self.timeout_seconds, int) or not 1 <= self.timeout_seconds <= 86_400:
            raise ValueError("timeout_seconds must be an integer between 1 and 86400")
        if not isinstance(self.max_output_bytes, int) or not 1_024 <= self.max_output_bytes <= 100_000_000:
            raise ValueError("max_output_bytes must be between 1024 and 100000000")
        if self.remote_repository is not None:
            _non_empty(self.remote_repository, "remote_repository")
        if self.idempotency_key is not None:
            _non_empty(self.idempotency_key, "idempotency_key")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SoftwareTask":
        if not isinstance(payload, Mapping):
            raise ValueError("software task must be an object")
        return cls(
            task_id=str(payload.get("task_id", "")),
            repository=str(payload.get("repository", "")),
            issue_url=str(payload.get("issue_url", "")),
            base_commit=str(payload.get("base_commit", "")),
            split=str(payload.get("split", "")),
            test_command=_command(payload.get("test_command"), "test_command"),
            acceptance_criteria=_strings(payload.get("acceptance_criteria"), "acceptance_criteria"),
            allowed_paths=_strings(payload.get("allowed_paths"), "allowed_paths"),
            hidden_test_command=(
                _command(payload.get("hidden_test_command"), "hidden_test_command")
                if payload.get("hidden_test_command") else ()
            ),
            hidden_test_asset=(
                str(payload["hidden_test_asset"])
                if payload.get("hidden_test_asset") is not None else None
            ),
            timeout_seconds=int(payload.get("timeout_seconds", 600)),
            max_output_bytes=int(payload.get("max_output_bytes", 2_000_000)),
            remote_repository=(str(payload["remote_repository"]) if payload.get("remote_repository") else None),
            idempotency_key=(str(payload["idempotency_key"]) if payload.get("idempotency_key") else None),
            schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "repository": self.repository,
            "issue_url": self.issue_url,
            "base_commit": self.base_commit,
            "split": self.split,
            "test_command": list(self.test_command),
            "hidden_test_command": list(self.hidden_test_command),
            "hidden_test_asset": self.hidden_test_asset,
            "acceptance_criteria": list(self.acceptance_criteria),
            "allowed_paths": list(self.allowed_paths),
            "timeout_seconds": self.timeout_seconds,
            "max_output_bytes": self.max_output_bytes,
            "remote_repository": self.remote_repository,
            "idempotency_key": self.idempotency_key,
        }

    def content_hash(self) -> str:
        encoded = json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


__all__ = ["SCHEMA_VERSION", "SoftwareTask"]
