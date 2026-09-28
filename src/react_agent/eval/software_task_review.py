"""公开 Issue 候选的进入门禁。

候选先经过此门禁得到 ``eligible`` 或缺失项，再交给任务集导入器；
没有自动猜测 Issue、commit 或测试内容。
"""
from __future__ import annotations

from typing import Any, Mapping


REQUIRED_REVIEW_FIELDS = (
    "issue_url", "base_commit", "public_test", "hidden_test",
    "allowed_paths", "license_confirmation", "runtime_image", "repository_cluster",
)


def _present(value: Any) -> bool:
    """接受非空文本或非空字符串数组，拒绝空容器和占位空值。"""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple)):
        return bool(value) and all(isinstance(item, str) and item.strip() for item in value)
    return False


def review_candidate(record: Mapping[str, Any]) -> dict[str, Any]:
    missing = [field for field in REQUIRED_REVIEW_FIELDS if not _present(record.get(field))]
    issue_url = str(record.get("issue_url") or "")
    base_commit = str(record.get("base_commit") or "")
    if issue_url and not (issue_url.startswith("https://github.com/") and "/issues/" in issue_url):
        missing.append("valid_issue_url")
    if base_commit and len(base_commit) < 7:
        missing.append("full_base_commit")
    return {"eligible": not missing, "missing": sorted(set(missing))}


__all__ = ["REQUIRED_REVIEW_FIELDS", "review_candidate"]
