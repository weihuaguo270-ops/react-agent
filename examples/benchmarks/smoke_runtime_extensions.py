"""本地验证 Runtime 扩展接口，不依赖外部模型或网络。"""
from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

from react_agent.server.app import AgentHandler
from run_http_benchmark import run as run_benchmark


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), AgentHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        body = json.dumps({"app": "docs_troubleshoot", "message": "upstream timeout 如何排查？"})
        conn = HTTPConnection(host, port, timeout=10)
        conn.request("POST", "/v1/chat/stream", body, {"Content-Type": "application/json"})
        stream = conn.getresponse()
        assert stream.status == 200
        assert b"event: started" in stream.read()
        conn.close()

        conn = HTTPConnection(host, port, timeout=10)
        conn.request("POST", "/v1/tasks", body, {"Content-Type": "application/json"})
        task = json.loads(conn.getresponse().read())
        conn.close()
        assert task["task_id"]

        conn = HTTPConnection(host, port, timeout=10)
        conn.request("GET", f"/v1/tasks/{task['task_id']}")
        status = json.loads(conn.getresponse().read())
        conn.close()
        assert status["status"] in {"queued", "running", "succeeded"}
        metrics = run_benchmark(f"http://{host}:{port}/v1/chat", total=5, concurrency=2, timeout=10)
        assert metrics["requests"] == 5
        print(json.dumps({"stream": "ok", "task": status["status"], "benchmark": metrics}, ensure_ascii=False))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
