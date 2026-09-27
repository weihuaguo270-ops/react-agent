"""任务集级别的历史软件任务清单与校验。

单条 ``SoftwareTask`` 只描述如何执行一个任务；本模块补充任务集的
来源、许可证、构建信息和 split 隔离规则。它不下载仓库，也不执行测试，
因此可以在没有网络或 Docker 的环境中先审查数据清单。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .software_task import SoftwareTask
from .software_task_review import review_candidate


DATASET_SCHEMA_VERSION = "software-task-dataset/v1"
_VALID_STATUS = {"active", "pending_external_data"}
_VALID_SOURCE_KINDS = {"external_issue"}
_REQUIRED_SOURCE_FIELDS = {"kind", "issue_url", "license", "provenance_url"}


class SoftwareTaskDatasetError(ValueError):
    """任务集违反可回放或来源约束。"""


def _text(value: Any, field: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise SoftwareTaskDatasetError(f"{field} must not be empty")
    return result


@dataclass(frozen=True)
class SoftwareTaskDataset:
    """可审计的软件任务集。

    ``tasks`` 保留为元组，序列化时按 task_id 排序，保证不同文件顺序产生
    相同哈希。任务本身仍由 ``SoftwareTask`` 完成字段和执行约束校验。
    """

    dataset_id: str
    version: str
    status: str
    license: str
    source_policy: str
    tasks: tuple[dict[str, Any], ...] = ()
    schema_version: str = DATASET_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != DATASET_SCHEMA_VERSION:
            raise SoftwareTaskDatasetError(
                f"unsupported schema_version: {self.schema_version}"
            )
        _text(self.dataset_id, "dataset_id")
        _text(self.version, "version")
        if self.status not in _VALID_STATUS:
            raise SoftwareTaskDatasetError(
                "status must be active or pending_external_data"
            )
        _text(self.license, "license")
        _text(self.source_policy, "source_policy")
        self._validate_tasks()
        if self.status == "active" and not self.tasks:
            raise SoftwareTaskDatasetError("active dataset must contain at least one task")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SoftwareTaskDataset":
        if not isinstance(payload, Mapping):
            raise SoftwareTaskDatasetError("dataset manifest must be an object")
        raw_tasks = payload.get("tasks", [])
        if not isinstance(raw_tasks, list):
            raise SoftwareTaskDatasetError("tasks must be an array")
        return cls(
            schema_version=str(payload.get("schema_version", "")),
            dataset_id=str(payload.get("dataset_id", "")),
            version=str(payload.get("version", "")),
            status=str(payload.get("status", "")),
            license=str(payload.get("license", "")),
            source_policy=str(payload.get("source_policy", "")),
            tasks=tuple(dict(item) for item in raw_tasks),
        )

    @classmethod
    def load(cls, path: str | Path) -> "SoftwareTaskDataset":
        manifest_path = Path(path)
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SoftwareTaskDatasetError(
                f"cannot load dataset manifest {manifest_path}: {exc}"
            ) from exc
        return cls.from_dict(payload)

    def _validate_tasks(self) -> None:
        seen_ids: set[str] = set()
        clusters_by_split: dict[str, set[str]] = {}
        for index, raw in enumerate(self.tasks):
            if not isinstance(raw, Mapping):
                raise SoftwareTaskDatasetError(f"tasks[{index}] must be an object")
            try:
                task = SoftwareTask.from_dict(raw)
            except (TypeError, ValueError) as exc:
                raise SoftwareTaskDatasetError(f"tasks[{index}] is invalid: {exc}") from exc
            if task.task_id in seen_ids:
                raise SoftwareTaskDatasetError(f"duplicate task_id: {task.task_id}")
            seen_ids.add(task.task_id)

            source = raw.get("source")
            if not isinstance(source, Mapping):
                raise SoftwareTaskDatasetError(f"tasks[{index}].source is required")
            missing = _REQUIRED_SOURCE_FIELDS - set(source)
            if missing:
                raise SoftwareTaskDatasetError(
                    f"tasks[{index}].source missing: {', '.join(sorted(missing))}"
                )
            if source.get("kind") not in _VALID_SOURCE_KINDS:
                raise SoftwareTaskDatasetError(
                    "only external_issue tasks are accepted; metadata/fixture tasks "
                    "must not be labelled as software tasks"
                )
            if str(source.get("issue_url", "")).strip() != task.issue_url:
                raise SoftwareTaskDatasetError(
                    f"tasks[{index}].source.issue_url must match issue_url"
                )
            _text(source.get("license"), f"tasks[{index}].source.license")
            _text(source.get("provenance_url"), f"tasks[{index}].source.provenance_url")

            cluster = str(raw.get("repository_cluster", "")).strip()
            if not cluster:
                raise SoftwareTaskDatasetError(
                    f"tasks[{index}].repository_cluster is required for split isolation"
                )
            clusters_by_split.setdefault(task.split, set()).add(cluster)

            build = raw.get("build")
            if not isinstance(build, Mapping):
                raise SoftwareTaskDatasetError(f"tasks[{index}].build is required")
            _text(build.get("runtime_image"), f"tasks[{index}].build.runtime_image")
            install = build.get("install", [])
            if not isinstance(install, list) or any(not str(item).strip() for item in install):
                raise SoftwareTaskDatasetError(
                    f"tasks[{index}].build.install must be a string array"
                )

            if task.split in {"golden", "held_out"} and not task.hidden_test_command:
                raise SoftwareTaskDatasetError(
                    f"tasks[{index}] in {task.split} requires hidden_test_command"
                )
            if task.split in {"golden", "held_out"} and not task.hidden_test_asset:
                raise SoftwareTaskDatasetError(
                    f"tasks[{index}] in {task.split} requires hidden_test_asset"
                )

        split_names = sorted(clusters_by_split)
        for left_index, left in enumerate(split_names):
            for right in split_names[left_index + 1 :]:
                overlap = clusters_by_split[left] & clusters_by_split[right]
                if overlap:
                    raise SoftwareTaskDatasetError(
                        "repository cluster crosses splits: " + ", ".join(sorted(overlap))
                    )

    def to_dict(self) -> dict[str, Any]:
        tasks = sorted((dict(task) for task in self.tasks), key=lambda item: item["task_id"])
        return {
            "schema_version": self.schema_version,
            "dataset_id": self.dataset_id,
            "version": self.version,
            "status": self.status,
            "license": self.license,
            "source_policy": self.source_policy,
            "tasks": tasks,
        }

    def content_hash(self) -> str:
        encoded = json.dumps(
            self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def split_counts(self) -> dict[str, int]:
        counts = {"dev": 0, "golden": 0, "held_out": 0}
        for task in self.tasks:
            counts[task["split"]] += 1
        return counts


def load_software_task_dataset(path: str | Path) -> SoftwareTaskDataset:
    """加载并完整校验一个历史软件任务集清单。"""

    return SoftwareTaskDataset.load(path)


def import_software_task_records(
    records_path: str | Path,
    output_path: str | Path,
    *,
    dataset_id: str = "public-history-software-tasks",
    version: str = "0.1.0",
    license: str = "CC-BY-4.0 (manifest); upstream repository licenses apply per task",
    source_policy: str = "Only publicly traceable issues with an explicit upstream license, frozen base commit, independent acceptance tests, and manual inclusion review.",
) -> SoftwareTaskDataset:
    """将人工审核的 JSON/JSONL 记录导入任务集清单。

    输入可以是一个任务数组，也可以是每行一条 JSON 记录。导入不会访问
    GitHub 或执行代码；所有来源、构建和 split 约束仍由清单校验器执行。
    """

    source = Path(records_path)
    try:
        text = source.read_text(encoding="utf-8")
        parsed = json.loads(text)
    except json.JSONDecodeError:
        try:
            parsed = [json.loads(line) for line in text.splitlines() if line.strip()]
        except json.JSONDecodeError as exc:
            raise SoftwareTaskDatasetError(f"invalid task records: {source}: {exc}") from exc
    if isinstance(parsed, Mapping):
        parsed = [parsed]
    if not isinstance(parsed, list):
        raise SoftwareTaskDatasetError("task records must be a JSON array or JSONL file")
    for index, raw in enumerate(parsed):
        if not isinstance(raw, Mapping):
            raise SoftwareTaskDatasetError(f"task records[{index}] must be an object")
        source = raw.get("source") if isinstance(raw.get("source"), Mapping) else {}
        build = raw.get("build") if isinstance(raw.get("build"), Mapping) else {}
        review = review_candidate({
            "issue_url": raw.get("issue_url"),
            "base_commit": raw.get("base_commit"),
            "public_test": raw.get("test_command"),
            "hidden_test": raw.get("hidden_test_command"),
            "allowed_paths": raw.get("allowed_paths"),
            "license_confirmation": source.get("license"),
            "runtime_image": build.get("runtime_image"),
            "repository_cluster": raw.get("repository_cluster"),
        })
        if not review["eligible"]:
            raise SoftwareTaskDatasetError(
                f"task records[{index}] failed review: {', '.join(review['missing'])}"
            )
    dataset = SoftwareTaskDataset(
        dataset_id=dataset_id,
        version=version,
        status="active",
        license=license,
        source_policy=source_policy,
        tasks=tuple(dict(item) for item in parsed),
    )
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(dataset.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return dataset


__all__ = [
    "DATASET_SCHEMA_VERSION",
    "SoftwareTaskDataset",
    "SoftwareTaskDatasetError",
    "load_software_task_dataset",
    "import_software_task_records",
]
