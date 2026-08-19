"""Run a small HTTP load test and emit latency, status, and resource evidence."""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import json
import math
import threading
import tracemalloc
import time
import urllib.error
import urllib.request
from collections import Counter
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * q) - 1))
    return round(ordered[index], 3)


def _request(url: str, body: bytes, timeout: float) -> dict[str, Any]:
    started = time.perf_counter()
    request = urllib.request.Request(
        f"{url.rstrip('/')}/v1/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read()
            status = response.status
            error = ""
    except urllib.error.HTTPError as exc:
        status = exc.code
        exc.read()
        error = "http_error"
    except Exception as exc:
        status = 0
        error = type(exc).__name__
    return {"status": status, "error": error, "latency_ms": (time.perf_counter() - started) * 1000}


def _rss_mb() -> float | None:
    try:
        import psutil  # type: ignore

        return round(psutil.Process().memory_info().rss / 1024 / 1024, 3)
    except Exception:
        pass
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class ProcessMemoryCounters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = ProcessMemoryCounters()
            counters.cb = ctypes.sizeof(counters)
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            ok = ctypes.windll.psapi.GetProcessMemoryInfo(
                handle, ctypes.byref(counters), counters.cb
            )
            if ok:
                return round(counters.WorkingSetSize / 1024 / 1024, 3)
        except Exception:
            return None
    return None


def run_http_benchmark(
    url: str,
    *,
    requests: int = 50,
    concurrency: int = 10,
    timeout: float = 30.0,
) -> dict[str, Any]:
    payload = json.dumps(
        {"app": "expense", "claim": {"category": "餐饮", "amount": 128, "has_receipt": True}},
        ensure_ascii=False,
    ).encode("utf-8")
    tracing_started = tracemalloc.is_tracing()
    if not tracing_started:
        tracemalloc.start()
    heap_before = tracemalloc.get_traced_memory()[0] / 1024 / 1024
    before_rss = _rss_mb()
    observed_rss = [before_rss] if before_rss is not None else []
    stop_sampling = threading.Event()

    def sample_resources() -> None:
        while not stop_sampling.wait(0.01):
            value = _rss_mb()
            if value is not None:
                observed_rss.append(value)

    sampler = threading.Thread(target=sample_resources, daemon=True)
    sampler.start()
    cpu_started = time.process_time()
    started = time.perf_counter()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
            rows = list(pool.map(lambda _: _request(url, payload, timeout), range(requests)))
    finally:
        stop_sampling.set()
        sampler.join(timeout=1)
    elapsed_ms = (time.perf_counter() - started) * 1000
    cpu_time_ms = (time.process_time() - cpu_started) * 1000
    after_rss = _rss_mb()
    heap_current, heap_peak = tracemalloc.get_traced_memory()
    if not tracing_started:
        tracemalloc.stop()
    if after_rss is not None:
        observed_rss.append(after_rss)
    latencies = [float(row["latency_ms"]) for row in rows]
    statuses = Counter(int(row["status"]) for row in rows)
    successful = sum(row["status"] == 200 for row in rows)
    return {
        "schema_version": "agent-http-benchmark/v1",
        "target": url,
        "load": {"requests": requests, "concurrency": concurrency, "timeout_s": timeout},
        "elapsed_ms": round(elapsed_ms, 3),
        "throughput_rps": round(requests / (elapsed_ms / 1000), 3) if elapsed_ms else 0.0,
        "success_rate": round(successful / requests, 4) if requests else 0.0,
        "error_rate": round(1 - successful / requests, 4) if requests else 1.0,
        "status_counts": dict(sorted(statuses.items())),
        "latency_ms": {
            "mean": round(sum(latencies) / len(latencies), 3) if latencies else 0.0,
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "p99": _percentile(latencies, 0.99),
            "max": round(max(latencies), 3) if latencies else 0.0,
        },
        "resource_observation": {
            "process_rss_before_mb": before_rss,
            "process_rss_after_mb": after_rss,
            "process_rss_peak_mb": max(observed_rss) if observed_rss else None,
            "process_cpu_time_ms": round(cpu_time_ms, 3),
            "process_cpu_to_wall_ratio": round(cpu_time_ms / elapsed_ms, 3) if elapsed_ms else 0.0,
            "python_heap_before_mb": round(heap_before, 3),
            "python_heap_after_mb": round(heap_current / 1024 / 1024, 3),
            "python_heap_peak_mb": round(heap_peak / 1024 / 1024, 3),
            "note": "Local mode runs HTTP server and load generator in one process; CPU and Python heap cover both. RSS is optional.",
        },
        "passed": successful == requests,
        "evidence_boundary": "Local HTTP load evidence for the tested target, request mix, and concurrency only; not a production SLA.",
    }


def _serve_local() -> tuple[ThreadingHTTPServer, threading.Thread]:
    import os

    os.environ.setdefault("REACT_AGENT_APP", "docs_troubleshoot")
    os.environ.setdefault("REACT_AGENT_DEFAULT_APP", "docs_troubleshoot")
    os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")
    os.environ.setdefault("REACT_AGENT_DISABLE_MCP", "1")
    from react_agent.server.app import AgentHandler
    from react_agent.tools import enable_app_tools

    enable_app_tools()
    server = ThreadingHTTPServer(("127.0.0.1", 0), AgentHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)
    return server, thread


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url")
    parser.add_argument("--requests", type=int, default=50)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    local: tuple[ThreadingHTTPServer, threading.Thread] | None = None
    if args.url:
        target = args.url
    else:
        local = _serve_local()
        target = f"http://127.0.0.1:{local[0].server_port}"
    try:
        report = run_http_benchmark(
            target, requests=args.requests, concurrency=args.concurrency, timeout=args.timeout
        )
    finally:
        if local:
            local[0].shutdown()
            local[0].server_close()
            local[1].join(timeout=5)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
