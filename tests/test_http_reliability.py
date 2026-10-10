import threading
from http.server import ThreadingHTTPServer

from tests._load_eval_script import load_eval_script
from react_agent.server.app import AgentHandler

_mod = load_eval_script("run_http_reliability")
probe_recovery = _mod.probe_recovery
run_reliability_suite = _mod.run_reliability_suite


def test_http_reliability_suite_reports_load_and_invalid_guard(monkeypatch, tmp_path):
    monkeypatch.setenv("REACT_AGENT_DATA_DIR", str(tmp_path))
    server = ThreadingHTTPServer(("127.0.0.1", 0), AgentHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        report = run_reliability_suite(f"http://127.0.0.1:{server.server_port}",
                                       requests=8, concurrency=4)
        assert report["passed"] is True
        assert report["success_rate"] == 1.0
        assert report["invalid_request_guard"]["statuses"] == [400, 400]
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_recovery_probe_observes_outage_then_recovers():
    holder = {}

    def restart():
        server = ThreadingHTTPServer(("127.0.0.1", holder["port"]), AgentHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        holder.update(server=server, thread=thread)
        thread.start()

    initial = ThreadingHTTPServer(("127.0.0.1", 0), AgentHandler)
    holder["port"] = initial.server_port
    initial.server_close()
    report = probe_recovery(f"http://127.0.0.1:{holder['port']}", restart, interval=0.01)
    try:
        assert report["outage_observed"] is True
        assert report["recovered"] is True
    finally:
        holder["server"].shutdown()
        holder["server"].server_close()
        holder["thread"].join(timeout=5)
