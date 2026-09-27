"""密钥脱敏（落盘/日志/事件流边界）。

轨迹文件、stdout 与 SSE 事件都会携带工具参数和观测结果。当工具参数或返回值
里出现凭据（API Key、Bearer Token、password 等）时，此前会原样持久化到
``%LOCALAPPDATA%\\react-agent\\trajectories`` 与 ``.tdebug/failures.jsonl``。

本模块提供统一脱敏，供 recorder / 日志 / SSE 边界复用。
"""
from __future__ import annotations

import json
import re

REDACTED = "<redacted>"

# 键名命中即整值替换（允许 key 前后有引号/空白）
_SENSITIVE_KEY_RE = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|apikey|access[_-]?key|"
    r"private[_-]?key|credential|authorization|cookie|session[_-]?id|bearer)\b"
)

# 值形态命中即局部替换（不依赖键名）
_URL_CREDENTIAL_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://[^\s:/@]+):([^\s:/@]+)@")

_VALUE_PATTERNS = (
    # OpenAI / DeepSeek 风格
    re.compile(r"\bsk-[A-Za-z0-9_\-]{12,}\b"),
    # GitHub PAT / OAuth
    re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    # AWS Access Key ID
    re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b"),
    # Slack
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b"),
    # Bearer / Basic 认证头
    re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._\-+/=]{16,}"),
)


def _redact_value(text: str) -> str:
    # scheme://user:pass@host -> 保留 scheme 与用户名，只抹掉口令
    text = _URL_CREDENTIAL_RE.sub(lambda m: f"{m.group(1)}:{REDACTED}@", text)
    for pattern in _VALUE_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def redact_text(text: str) -> str:
    """对自由文本做值形态脱敏（日志/观测/思考）。"""
    if not text:
        return text
    if not isinstance(text, str):
        text = str(text)
    return _redact_value(text)


def redact_arguments(arguments) -> str:
    """对工具参数做脱敏，保留结构便于排障。

    ``arguments`` 通常是 JSON 字符串；解析失败时退化为整体文本脱敏。
    """
    if arguments is None:
        return ""
    if not isinstance(arguments, str):
        try:
            arguments = json.dumps(arguments, ensure_ascii=False)
        except (TypeError, ValueError):
            arguments = str(arguments)

    try:
        parsed = json.loads(arguments)
    except (json.JSONDecodeError, TypeError):
        return redact_text(arguments)

    def walk(node, key_hint: str = ""):
        if isinstance(node, dict):
            return {
                k: (REDACTED if _SENSITIVE_KEY_RE.search(str(k)) else walk(v, str(k)))
                for k, v in node.items()
            }
        if isinstance(node, list):
            return [walk(item, key_hint) for item in node]
        if isinstance(node, str):
            if key_hint and _SENSITIVE_KEY_RE.search(key_hint):
                return REDACTED
            return redact_text(node)
        return node

    try:
        return json.dumps(walk(parsed), ensure_ascii=False)
    except (TypeError, ValueError):
        return redact_text(arguments)
