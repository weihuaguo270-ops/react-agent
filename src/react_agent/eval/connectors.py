"""企业数据源的只读采集器和统一任务格式。"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


JsonTransport = Callable[[str, Mapping[str, str]], tuple[Any, Mapping[str, str]]]


def load_env_file(path: Path, *, override: bool = False) -> int:
    """读取简单 ``KEY=VALUE`` 文件；默认不覆盖已有进程环境变量。"""
    if not path.exists():
        return 0
    loaded = 0
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = (item.strip() for item in line.split("=", 1))
        if not key or (not override and key in os.environ):
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value
        loaded += 1
    return loaded


@dataclass(frozen=True)
class ConnectorConfig:
    """只读连接配置；token 只从环境变量读取，不写入采集结果。"""

    base_url: str
    token: str
    timeout_seconds: int = 30
    auth_header: str = "Authorization"
    auth_scheme: str = "Bearer"

    @classmethod
    def from_env(cls, prefix: str) -> "ConnectorConfig":
        """按 ``PREFIX_BASE_URL`` 和 ``PREFIX_READONLY_TOKEN`` 读取配置。"""
        base_url = os.environ.get(f"{prefix}_BASE_URL", "").strip().rstrip("/")
        token = os.environ.get(f"{prefix}_READONLY_TOKEN", "").strip()
        if not base_url or not token:
            raise ValueError(f"missing {prefix}_BASE_URL or {prefix}_READONLY_TOKEN")
        return cls(
            base_url=base_url,
            token=token,
            auth_header=os.environ.get(f"{prefix}_AUTH_HEADER", "Authorization").strip(),
            auth_scheme=os.environ.get(f"{prefix}_AUTH_SCHEME", "Bearer").strip(),
        )


class ReadOnlyHttpClient:
    """只允许 GET 的标准库 HTTP 客户端。"""

    def __init__(self, config: ConnectorConfig, transport: JsonTransport | None = None):
        self.config = config
        self._transport = transport
        self.audit: list[dict[str, Any]] = []

    def get(self, path: str, params: Mapping[str, str] | None = None) -> tuple[Any, Mapping[str, str]]:
        """发起 GET 请求并返回 JSON 和响应头；不会暴露 token。"""
        query = f"?{urlencode(params)}" if params else ""
        target = f"{self.config.base_url}/{path.lstrip('/')}{query}"
        headers = {"Accept": "application/json", "User-Agent": "react-agent-readonly"}
        if self._transport:
            payload, response_headers = self._transport(target, headers)
            self._record_audit(target, response_headers)
            return payload, response_headers
        credential = " ".join(
            item for item in (self.config.auth_scheme, self.config.token) if item
        )
        request = Request(
            target,
            headers={**headers, self.config.auth_header: credential},
        )
        with urlopen(request, timeout=self.config.timeout_seconds) as response:
            response_headers = dict(response.headers.items())
            self._record_audit(target, response_headers)
            return json.loads(response.read().decode("utf-8")), response_headers

    def _record_audit(self, target: str, headers: Mapping[str, str]) -> None:
        """记录不含认证信息的请求地址和上游请求标识。"""
        request_id = next(
            (
                value
                for key, value in headers.items()
                if key.lower() in {"x-request-id", "x-gitlab-trace-id", "x-servicenow-request-id"}
            ),
            None,
        )
        self.audit.append({"method": "GET", "url": target, "request_id": request_id})


class BaseAdapter:
    """连接器基类：负责分页，子类只实现来源字段映射。"""

    domain = "unknown"

    def __init__(self, client: ReadOnlyHttpClient, *, max_items: int = 100):
        self.client = client
        self.max_items = max_items

    def fetch(self) -> list[dict[str, Any]]:
        """读取并转换任务；返回值不含 baseline/candidate，需后续 Agent 填充。"""
        records = self._fetch_records()
        return [self.normalize(record) for record in records[: self.max_items]]

    def _fetch_records(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def normalize(self, record: Mapping[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def _task(self, task_id: Any, text: Any, source_ref: str, status: Any = None) -> dict[str, Any]:
        final_status = self._status(status)
        return {
            "task_id": str(task_id),
            "domain": self.domain,
            "input": str(text or ""),
            "split": "dev",
            "redaction": {"applied": False},
            "source_status": str(status or "unknown"),
            "final_status": final_status,
            "evidence": {"source_ref": source_ref, "source_type": self.__class__.__name__},
        }

    @staticmethod
    def _status(value: Any) -> str:
        """将未关闭状态标记为待复核，避免误称为已解决。"""
        return "resolved" if str(value or "").lower() in {"done", "closed", "resolved", "solved", "6", "7"} else "needs_review"


class JiraAdapter(BaseAdapter):
    """Jira REST API v3 的只读 Issue 采集器。"""

    domain = "software_delivery"

    def __init__(self, client: ReadOnlyHttpClient, *, jql: str = "order by updated DESC", max_items: int = 100):
        super().__init__(client, max_items=max_items)
        self.jql = jql

    def _fetch_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        start_at = 0
        while len(records) < self.max_items:
            payload, _ = self.client.get(
                "/rest/api/3/search",
                {"jql": self.jql, "startAt": str(start_at), "maxResults": "50"},
            )
            page = list((payload or {}).get("issues") or [])
            records.extend(page)
            if len(page) == 0 or start_at + len(page) >= int((payload or {}).get("total", len(records))):
                break
            start_at += len(page)
        return records

    def normalize(self, record: Mapping[str, Any]) -> dict[str, Any]:
        fields = record.get("fields") or {}
        status = (fields.get("status") or {}).get("statusCategory", {}).get("key")
        return self._task(
            record.get("key"),
            fields.get("summary") or fields.get("description"),
            f"{self.client.config.base_url}/browse/{record.get('key', '')}",
            status,
        )


class GitLabAdapter(BaseAdapter):
    """GitLab Issues API 的只读采集器。"""

    domain = "software_delivery"

    def __init__(self, client: ReadOnlyHttpClient, project_id: str, *, max_items: int = 100):
        super().__init__(client, max_items=max_items)
        self.project_id = project_id

    def _fetch_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        page = 1
        while len(records) < self.max_items:
            payload, headers = self.client.get(
                f"/api/v4/projects/{self.project_id}/issues",
                {"state": "all", "page": str(page), "per_page": "50"},
            )
            current = list(payload or [])
            records.extend(current)
            next_page = str(headers.get("X-Next-Page") or "")
            if not current or not next_page:
                break
            page = int(next_page)
        return records

    def normalize(self, record: Mapping[str, Any]) -> dict[str, Any]:
        return self._task(
            record.get("iid") or record.get("id"),
            record.get("title") or record.get("description"),
            str(record.get("web_url") or ""),
            record.get("state"),
        )


class ZendeskAdapter(BaseAdapter):
    """Zendesk Tickets API 的只读采集器。"""

    domain = "technical_support"

    def _fetch_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        page = 1
        while len(records) < self.max_items:
            payload, _ = self.client.get(
                "/api/v2/tickets.json",
                {"per_page": "100", "page": str(page)},
            )
            current = list((payload or {}).get("tickets") or [])
            records.extend(current)
            if not current or not (payload or {}).get("next_page"):
                break
            page += 1
        return records

    def normalize(self, record: Mapping[str, Any]) -> dict[str, Any]:
        return self._task(
            record.get("id"),
            record.get("subject") or record.get("description"),
            f"{self.client.config.base_url}/agent/tickets/{record.get('id', '')}",
            record.get("status"),
        )


class ServiceNowAdapter(BaseAdapter):
    """ServiceNow Table API 的只读 Incident 采集器。"""

    domain = "technical_support"

    def __init__(self, client: ReadOnlyHttpClient, *, table: str = "incident", max_items: int = 100):
        super().__init__(client, max_items=max_items)
        self.table = table

    def _fetch_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        offset = 0
        while len(records) < self.max_items:
            payload, _ = self.client.get(
                f"/api/now/table/{self.table}",
                {"sysparm_limit": "100", "sysparm_offset": str(offset)},
            )
            page = list((payload or {}).get("result") or [])
            records.extend(page)
            if len(page) < 100:
                break
            offset += len(page)
        return records

    def normalize(self, record: Mapping[str, Any]) -> dict[str, Any]:
        number = record.get("number") or record.get("sys_id")
        return self._task(
            number,
            record.get("short_description") or record.get("description"),
            f"{self.client.config.base_url}/nav_to.do?uri={self.table}.do?sys_id={record.get('sys_id', '')}",
            record.get("state"),
        )


class TraceAdapter(BaseAdapter):
    """通过 trace 查询接口读取 APM/日志事件的通用适配器。"""

    domain = "technical_support"

    def __init__(self, client: ReadOnlyHttpClient, query_path: str, *, trace_ids: list[str], max_items: int = 100):
        super().__init__(client, max_items=max_items)
        self.query_path = query_path
        self.trace_ids = trace_ids

    def _fetch_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for trace_id in self.trace_ids:
            payload, _ = self.client.get(self.query_path, {"trace_id": trace_id})
            if isinstance(payload, list):
                records.extend(payload)
            elif isinstance(payload, Mapping):
                records.append(dict(payload))
        return records

    def normalize(self, record: Mapping[str, Any]) -> dict[str, Any]:
        trace_id = record.get("trace_id") or record.get("id")
        text = record.get("error") or record.get("message") or record.get("status")
        return self._task(trace_id, text, f"trace://{trace_id}", record.get("status"))


__all__ = [
    "BaseAdapter",
    "ConnectorConfig",
    "GitLabAdapter",
    "JiraAdapter",
    "load_env_file",
    "ReadOnlyHttpClient",
    "ServiceNowAdapter",
    "TraceAdapter",
    "ZendeskAdapter",
]
