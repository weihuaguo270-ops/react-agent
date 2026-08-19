"""测量 Agent HTTP 服务的延迟、吞吐和错误率。

示例：
    python examples/benchmarks/run_http_benchmark.py --url http://127.0.0.1:8765 --requests 50 --concurrency 10
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib import request


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    index = min(len(values) - 1, max(0, int(round((len(values) - 1) * q))))
    return values[index]


def _one(url: str, body: dict, timeout: float) -> tuple[float, int | None]:
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = request.Request(url, data=raw, headers={"Content-Type": "application/json"}, method="POST")
    started = time.perf_counter()
    try:
        with request.urlopen(req, timeout=timeout) as response:
            response.read()
            return (time.perf_counter() - started) * 1000, response.status
    except Exception:
        return (time.perf_counter() - started) * 1000, None


def run(url: str, total: int, concurrency: int, timeout: float) -> dict:
    body = {"app": "docs_troubleshoot", "message": "upstream timeout 如何排查？"}
    latencies: list[float] = []
    statuses: list[int] = []
    wall_started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = [pool.submit(_one, url, body, timeout) for _ in range(total)]
        for future in as_completed(futures):
            latency, status = future.result()
            latencies.append(latency)
            if status is not None:
                statuses.append(status)
    elapsed = time.perf_counter() - wall_started
    success = sum(status == 200 for status in statuses)
    return {
        "requests": total,
        "concurrency": concurrency,
        "success": success,
        "errors": total - success,
        "success_rate": success / total if total else 0.0,
        "throughput_rps": total / elapsed if elapsed else 0.0,
        "latency_ms": {
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "p99": _percentile(latencies, 0.99),
            "mean": statistics.mean(latencies) if latencies else 0.0,
        },
        "status_codes": {str(code): statuses.count(code) for code in sorted(set(statuses))},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent HTTP 延迟/吞吐基准")
    parser.add_argument("--url", default="http://127.0.0.1:8765/v1/chat")
    parser.add_argument("--requests", type=int, default=50)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    print(json.dumps(run(args.url, args.requests, args.concurrency, args.timeout), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
