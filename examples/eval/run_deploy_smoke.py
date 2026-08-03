"""Post-deploy smoke — health, ready, offline chat, workflow list."""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def _get(url: str) -> tuple[int, dict]:
    with urllib.request.urlopen(url, timeout=10) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def _post(url: str, body: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def main() -> int:
    p = argparse.ArgumentParser(description="Deploy smoke for react-agent HTTP server")
    p.add_argument("--url", default="http://127.0.0.1:8765", help="Base URL")
    args = p.parse_args()
    base = args.url.rstrip("/")
    ok = True

    status, health = _get(f"{base}/health")
    print(f"[deploy] health {status} -> {health.get('status')} v{health.get('version')}")
    ok &= status == 200 and health.get("status") == "ok"

    status, ready = _get(f"{base}/ready")
    print(f"[deploy] ready  {status} -> {ready.get('status')} chunks={ready.get('chunks')}")
    ok &= status == 200 and ready.get("status") == "ready"

    status, chat = _post(f"{base}/v1/chat", {"message": "缺少 Authorization 返回什么？"})
    ans = chat.get("answer", "")
    print(f"[deploy] chat   {status} mode={chat.get('mode')} refused={chat.get('refused')}")
    ok &= status == 200 and ("401" in ans or "unauthorized" in ans.lower())

    status, wfs = _get(f"{base}/v1/workflows")
    names = [w.get("name") for w in wfs.get("workflows", [])]
    print(f"[deploy] workflows {status} -> {names}")
    ok &= status == 200 and "docs_troubleshoot" in names

    print(f"[deploy] overall={'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
