"""Measure a deployed Agent HTTP service under concurrent and invalid traffic."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import time
import urllib.error
import urllib.request
from pathlib import Path


def _request(url, body):
    started = time.perf_counter()
    request = urllib.request.Request(f"{url.rstrip('/')}/v1/chat", data=body,
                                     headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status, payload = response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        status, payload = error.code, json.loads(error.read().decode("utf-8"))
    except Exception as error:
        status, payload = 0, {"error": type(error).__name__, "detail": str(error)}
    return {"status": status, "latency_ms": (time.perf_counter() - started) * 1000, "payload": payload}


def run_reliability_suite(url, *, requests=30, concurrency=5):
    valid = json.dumps({"app": "expense", "claim": {"category": "餐饮", "amount": 128,
                        "has_receipt": True}}, ensure_ascii=False).encode("utf-8")
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        results = list(pool.map(lambda _: _request(url, valid), range(requests)))
    invalid = [_request(url, b"{bad json"), _request(url, b"[]")]
    latencies = sorted(row["latency_ms"] for row in results)
    success = sum(row["status"] == 200 and row["payload"].get("decision") == "approve_manager"
                  for row in results)
    invalid_ok = all(row["status"] == 400 for row in invalid)
    p95_index = max(0, math.ceil(len(latencies) * 0.95) - 1)
    return {"schema_version": "agent-service-reliability/v1", "target": url,
            "load": {"requests": requests, "concurrency": concurrency},
            "success_rate": success / requests if requests else 0.0,
            "error_rate": 1 - success / requests if requests else 1.0,
            "latency_ms": {"mean": sum(latencies) / len(latencies), "p95": latencies[p95_index]},
            "invalid_request_guard": {"passed": invalid_ok, "statuses": [row["status"] for row in invalid]},
            "passed": success == requests and invalid_ok,
            "evidence_boundary": "Deployment reliability evidence for the tested target and load only."}


def probe_recovery(url, restart_callback, *, attempts=20, interval=0.1):
    """Verify a dependency outage is visible and service recovery is bounded."""
    unavailable = _request(url, b"{}")
    started = time.perf_counter()
    restart_callback()
    recovered = None
    for attempt in range(1, attempts + 1):
        time.sleep(interval)
        result = _request(url, json.dumps({"app": "expense", "claim": {
            "category": "餐饮", "amount": 128, "has_receipt": True}},
            ensure_ascii=False).encode("utf-8"))
        if result["status"] == 200:
            recovered = {"attempt": attempt, "result": result}
            break
    return {"outage_observed": unavailable["status"] == 0,
            "recovered": recovered is not None,
            "recovery_time_ms": (time.perf_counter() - started) * 1000,
            "attempt": recovered["attempt"] if recovered else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--requests", type=int, default=30)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = run_reliability_suite(args.url, requests=args.requests, concurrency=args.concurrency)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
