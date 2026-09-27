"""Field evidence parsing for docs troubleshoot (P1)."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

_REDACT_KEYS = re.compile(r"(authorization|api[_-]?key|token|secret|password)", re.I)

_SAFE_ENV_PREFIXES = ("REACT_AGENT_", "LLM_", "RAG_")


def _parse_json_blob(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {"value": data}
        except json.JSONDecodeError:
            return {"raw": raw[:500]}
    return {}


def redact_headers(headers: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in headers.items():
        key = str(k)
        val = str(v)
        if _REDACT_KEYS.search(key):
            out[key] = "<redacted>"
        else:
            out[key] = val[:200]
    return out


def parse_error_evidence(
    *,
    status_code: int = 0,
    body_json: str = "",
) -> dict[str, Any]:
    """Parse HTTP error response into structured evidence."""
    body = _parse_json_blob(body_json)
    err = body.get("error") if isinstance(body.get("error"), dict) else body
    code = ""
    message = ""
    if isinstance(err, dict):
        code = str(err.get("code") or "")
        message = str(err.get("message") or "")
    return {
        "ok": True,
        "type": "http_error",
        "status_code": int(status_code or 0),
        "error_code": code,
        "message": message[:300],
        "body": body,
    }


def parse_request_headers(headers_json: str = "") -> dict[str, Any]:
    data = _parse_json_blob(headers_json)
    redacted = redact_headers(data) if data else {}
    has_auth = any(
        k.lower() == "authorization" and v and v != "<redacted>"
        for k, v in redacted.items()
    )
    has_bearer = any(
        "bearer" in str(v).lower() for k, v in redacted.items() if k.lower() == "authorization"
    )
    return {
        "ok": True,
        "type": "request_headers",
        "headers": redacted,
        "has_authorization": has_auth or "authorization" in {k.lower() for k in data},
        "has_bearer": has_bearer,
    }


def read_config_snapshot(prefixes: str = "REACT_AGENT_") -> dict[str, Any]:
    """Read non-secret env vars matching prefixes (comma-separated).

    前缀受限于 ``REACT_AGENT_`` 命名空间：调用方可控的 prefixes 否则可以指向
    任意宿主变量（例如 ``A`` 命中 ``AWS_ACCESS_KEY_ID``），而 ``_REDACT_KEYS``
    只覆盖名字里含 secret/token/password/api_key 的键。
    """
    allowed_prefix = "REACT_AGENT_"
    raw_prefixes = [p.strip() for p in (prefixes or allowed_prefix).split(",") if p.strip()]
    pfx = [p for p in raw_prefixes if p.startswith(allowed_prefix)]
    rejected = [p for p in raw_prefixes if not p.startswith(allowed_prefix)]
    if not pfx:
        return {
            "ok": False,
            "type": "config_snapshot",
            "error": f"prefixes 必须位于 {allowed_prefix} 命名空间内",
            "rejected": rejected,
        }
    snap: dict[str, str] = {}
    for key, val in sorted(os.environ.items()):
        if not any(key.startswith(p) for p in pfx):
            continue
        if _REDACT_KEYS.search(key):
            snap[key] = "<redacted>"
        else:
            snap[key] = val[:120]
    result: dict[str, Any] = {"ok": True, "type": "config_snapshot", "env": snap}
    if rejected:
        result["rejected_prefixes"] = rejected
    return result


def _self_health_target(target: str) -> str | None:
    """判断目标是否是「本服务自身的健康端点」。

    若是，返回 ``"liveness"`` / ``"readiness"``，调用方改为**进程内**取值，
    不再经 TCP 回环请求自己——那既浪费也会与探针鉴权/Host 校验策略耦合。
    """
    try:
        parsed = urlparse(target)
    except ValueError:
        return None
    if (parsed.scheme or "").lower() not in ("http", "https"):
        return None
    host = (parsed.hostname or "").lower()
    if host not in ("127.0.0.1", "localhost", "::1"):
        return None
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    # 仅当端口与本服务配置端口一致才视为自探，避免误判同端口的其它服务
    configured = os.environ.get("REACT_AGENT_PORT", "8765").strip() or "8765"
    if str(port) != configured:
        return None
    path = (parsed.path or "/").rstrip("/") or "/"
    if path in ("/health", "/v1/health"):
        return "liveness"
    if path in ("/ready", "/v1/ready"):
        return "readiness"
    return None


def _in_process_health(kind: str, target: str) -> dict[str, Any]:
    """进程内读取健康状态，返回与 HTTP 探活同形的结果。"""
    try:
        if kind == "liveness":
            import uuid as _uuid

            from react_agent.server.health import liveness_payload

            status_code = 200
            body = json.dumps(
                liveness_payload(request_id=str(_uuid.uuid4())), ensure_ascii=False
            )
        else:
            from react_agent.server.health import readiness_check

            ready, payload = readiness_check()
            status_code = 200 if ready else 503
            body = json.dumps(payload, ensure_ascii=False)
    except Exception as exc:  # 与 HTTP 路径保持一致：失败也返回结构化结果
        return {
            "ok": False,
            "type": "health_probe",
            "url": target,
            "in_process": True,
            "error": str(exc)[:200],
        }
    return {
        "ok": True,
        "type": "health_probe",
        "url": target,
        "status_code": status_code,
        "body_preview": body[:400],
        "in_process": True,
        "probe_kind": kind,
    }


def probe_service_health(url: str = "", timeout_sec: float = 3.0) -> dict[str, Any]:
    target = (url or os.environ.get("REACT_AGENT_HEALTH_URL") or "http://127.0.0.1:8765/health").strip()
    if not target:
        return {"ok": False, "type": "health_probe", "error": "no_url"}

    # 自探走进程内：不产生回环 HTTP，也不依赖探针的鉴权/Host 策略
    self_kind = _self_health_target(target)
    if self_kind is not None:
        return _in_process_health(self_kind, target)

    # SSRF 守卫：只允许 http/https，且解析后的 IP 不得是内网/保留地址；
    # 本函数的默认目标是回环地址，属于显式放行的运维用途。
    from react_agent.safety.net_guard import build_opener, validate_url

    loopback_default = target == "http://127.0.0.1:8765/health" and not url
    if not loopback_default:
        ok, reason = validate_url(target)
        if not ok:
            return {"ok": False, "type": "health_probe", "url": target, "error": f"blocked: {reason}"}
    req = urllib.request.Request(target, method="GET")
    try:
        with build_opener().open(req, timeout=timeout_sec) as resp:
            body = resp.read(4096).decode("utf-8", errors="replace")
            return {
                "ok": True,
                "type": "health_probe",
                "url": target,
                "status_code": resp.status,
                "body_preview": body[:400],
            }
    except urllib.error.HTTPError as e:
        return {
            "ok": True,
            "type": "health_probe",
            "url": target,
            "status_code": e.code,
            "body_preview": (e.read(512).decode("utf-8", errors="replace") if e.fp else ""),
        }
    except Exception as e:
        return {"ok": False, "type": "health_probe", "url": target, "error": str(e)[:200]}


_TRACE_ID_RE = re.compile(r"\btrace[_-]?id[=:\s\"]+([a-zA-Z0-9_-]{6,64})", re.I)
_REQUEST_ID_RE = re.compile(r"\brequest[_-]?id[=:\s\"]+([a-zA-Z0-9_-]{4,64})", re.I)


def parse_log_evidence(
    log_text: str = "",
    *,
    trace_id: str = "",
    max_highlights: int = 8,
) -> dict[str, Any]:
    """Parse log excerpt; highlight lines matching trace_id or error signals."""
    lines = (log_text or "").splitlines()
    tid = (trace_id or "").strip()
    highlights: list[str] = []
    found_trace = tid
    found_request = ""

    for line in lines:
        raw = line.strip()
        if not raw:
            continue
        if not found_trace:
            m = _TRACE_ID_RE.search(raw)
            if m:
                found_trace = m.group(1)
        m = _REQUEST_ID_RE.search(raw)
        if m:
            found_request = m.group(1)
        keep = False
        if tid and tid in raw:
            keep = True
        elif re.search(
            r"\b(ERROR|WARN|error\.code|upstream_timeout|rate_limited|unauthorized|504|429|401)\b",
            raw,
            re.I,
        ):
            keep = True
        if keep:
            highlights.append(raw[:320])

    if not highlights and lines:
        highlights = [ln.strip()[:320] for ln in lines[:3] if ln.strip()]

    return {
        "ok": True,
        "type": "log_excerpt",
        "trace_id": found_trace or tid,
        "request_id": found_request,
        "highlights": highlights[:max_highlights],
        "line_count": len(lines),
    }


def parse_trace_context(trace_json: str = "") -> dict[str, Any]:
    """Parse distributed trace JSON (OpenTelemetry-ish or simple spans list)."""
    data = _parse_json_blob(trace_json)
    spans: list[dict[str, Any]] = []
    if isinstance(data.get("spans"), list):
        raw_spans = data["spans"]
    elif isinstance(data.get("trace"), dict) and isinstance(data["trace"].get("spans"), list):
        raw_spans = data["trace"]["spans"]
    else:
        raw_spans = [data] if data else []

    for sp in raw_spans:
        if not isinstance(sp, dict):
            continue
        spans.append(
            {
                "name": str(sp.get("name") or sp.get("operation") or "")[:120],
                "service": str(sp.get("service") or sp.get("serviceName") or "")[:80],
                "status": sp.get("status") or sp.get("statusCode"),
                "error": sp.get("error") or sp.get("errorMessage"),
            }
        )

    err_spans = [s for s in spans if s.get("error")]
    return {
        "ok": True,
        "type": "trace_context",
        "span_count": len(spans),
        "error_span_count": len(err_spans),
        "spans": spans[:12],
        "trace_id": str(data.get("trace_id") or data.get("traceId") or "")[:64],
    }


def collect_evidence_bundle(state: dict[str, Any]) -> dict[str, Any]:
    """Merge optional workflow state fields into one evidence bundle."""
    items: list[dict[str, Any]] = []
    err = state.get("error_response")
    if err:
        if isinstance(err, dict):
            items.append(
                parse_error_evidence(
                    status_code=int(err.get("status_code") or err.get("status") or 0),
                    body_json=json.dumps(err.get("body") or err, ensure_ascii=False),
                )
            )
        elif isinstance(err, str):
            items.append(parse_error_evidence(body_json=err))
    hdr = state.get("request_headers")
    if hdr:
        items.append(
            parse_request_headers(
                headers_json=hdr if isinstance(hdr, str) else json.dumps(hdr, ensure_ascii=False)
            )
        )
    if state.get("include_config_snapshot"):
        items.append(read_config_snapshot(str(state.get("config_prefixes") or "REACT_AGENT_")))
    if state.get("run_health_check"):
        items.append(probe_service_health(str(state.get("health_url") or "")))
    log_text = state.get("log_excerpt") or state.get("log_text")
    if log_text:
        items.append(
            parse_log_evidence(
                str(log_text),
                trace_id=str(state.get("trace_id") or ""),
            )
        )
    trace = state.get("trace_context")
    if trace:
        items.append(
            parse_trace_context(
                trace if isinstance(trace, str) else json.dumps(trace, ensure_ascii=False)
            )
        )
    tid = str(state.get("trace_id") or "").strip()
    fetch_trace = state.get("fetch_trace_from_backend", True)
    has_trace = any(i.get("type") == "trace_context" for i in items)
    if tid and fetch_trace and not has_trace:
        from react_agent.apps.docs_troubleshoot.trace_backend import (
            fetch_trace_bundle,
            trace_bundle_to_evidence_items,
        )

        bundle = fetch_trace_bundle(tid)
        items.extend(trace_bundle_to_evidence_items(bundle))
    return {"items": items, "count": len(items)}
