"""Exercise the local Compose task stack and retain a recoverable Redis backup.

Run only on the local development stack: it briefly stops its Worker and Redis.
The API, Worker, PostgreSQL and Redis must already be built and started.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]


def docker(*args: str) -> str:
    result = subprocess.run(["docker", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"docker {args[0]} failed: {result.stderr[-1500:]}")
    return (result.stdout + result.stderr).strip() if args[0] == "logs" else result.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:8766")
    args = parser.parse_args()
    run_id = "mvp-" + uuid.uuid4().hex[:10]
    output = ROOT / "artifacts" / "redis-task-mvp" / run_id
    output.mkdir(parents=True)
    report = {"run_id": run_id, "started_at": datetime.now(timezone.utc).isoformat(), "checks": {}}
    api = docker("compose", "ps", "-q", "docs-troubleshoot")
    redis = docker("compose", "ps", "-q", "redis")
    worker = docker("compose", "ps", "-q", "worker")
    if not all([api, redis, worker]):
        raise RuntimeError("Start the Compose API, Redis and Worker before verification")
    worker_stopped = redis_stopped = False
    restore_containers = []

    def check(name, detail):
        report["checks"][name] = {"passed": True, "detail": detail}
        print(f"PASS {name}", flush=True)

    def request(method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = Request(args.api_url + path, data=data, method=method, headers={"Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=20) as response:
                return response.status, json.load(response)
        except HTTPError as exc:
            return exc.code, json.load(exc)

    def await_api():
        for _ in range(60):
            try:
                if request("GET", "/health")[0] == 200:
                    return
            except (URLError, OSError):
                pass
            time.sleep(1)
        raise AssertionError("API failed to become ready")

    def task(task_id, expected):
        for _ in range(60):
            status, value = request("GET", f"/v1/tasks/{task_id}")
            assert status == 200, value
            if value["status"] == expected:
                return value
            time.sleep(0.5)
        raise AssertionError(f"Task did not reach {expected}: {value}")

    def api_python(code):
        return docker("exec", api, "python", "-c", code)

    def redis_cli(*command):
        return docker("exec", redis, "redis-cli", "--raw", *command)

    try:
        await_api()
        docker("stop", worker)
        worker_stopped = True
        status, submitted = request("POST", "/v1/tasks", {"message": "HTTP 401", "app": "docs_troubleshoot"})
        assert status == 202 and submitted["status"] == "queued", submitted
        task_id = submitted["task_id"]
        assert task(task_id, "queued")["started_at"] is None
        check("api_does_not_execute_task", {"task_id": task_id, "status": status})
        status, cancelled = request("POST", "/v1/tasks", {"message": "cancel before execute"})
        assert status == 202
        cancelled_id = cancelled["task_id"]
        status, value = request("DELETE", f"/v1/tasks/{cancelled_id}")
        assert status == 200 and value["status"] == "cancelled"
        docker("start", worker)
        worker_stopped = False
        completed = task(task_id, "succeeded")
        assert completed["started_at"] is not None and completed["result"]["http_status"] == 200
        assert task(cancelled_id, "cancelled")["started_at"] is None
        check("worker_success_and_queued_cancel", {"task_id": task_id, "cancelled_id": cancelled_id})
        status, failure = request("POST", "/v1/tasks", {"message": "failure", "app": "unknown-audit-app"})
        assert status == 202
        assert task(failure["task_id"], "failed")["error"]
        check("worker_http_failure", {"task_id": failure["task_id"]})
        docker("restart", api)
        await_api()
        assert task(task_id, "succeeded")["result"] == completed["result"]
        check("api_restart_persistence", {"task_id": task_id})

        # A terminated consumer leaves a pending message; another consumer
        # reclaims it using the actual RedisTaskQueue implementation.
        reclaimed = json.loads(api_python(f"""
import json, os, time
from react_agent.server.redis_queue import RedisTaskQueue
os.environ['REACT_AGENT_QUEUE_VISIBILITY_MS'] = '50'
q1 = RedisTaskQueue(stream='{run_id}:claim', group='audit', consumer='terminated')
q2 = RedisTaskQueue(stream='{run_id}:claim', group='audit', consumer='replacement')
q1.enqueue('reclaim-task', {{'body': {{'message': 'audit'}}, 'request_id': 'audit'}})
first = q1.read(block_ms=1)
time.sleep(0.1)
second = q2.claim_pending()
assert first == second
q2.ack(second[0])
assert q2.queue_length() == 0
q2.client.delete(q2.stream)
print(json.dumps({{'first': first[0], 'reclaimed': second[0]}}))
"""))
        check("pending_reclaim_other_consumer", reclaimed)

        api_python(f"""
import time
from react_agent.server.redis_queue import RedisTaskQueue
from react_agent.server.sqlalchemy_store import PostgreSQLTaskStore
from react_agent.server.task_manager import TaskRecord
from react_agent.worker import process_message
s = PostgreSQLTaskStore()
q = RedisTaskQueue(stream='{run_id}:duplicate', group='audit')
record = TaskRecord('{run_id}-fence')
s.save(record)
old = s.claim(record.task_id, now=time.time()-2, visibility_seconds=1)
new = s.claim(record.task_id, now=time.time(), visibility_seconds=1)
assert old is not None and new is not None
new.status = 'succeeded'
new.result = {{'attempt': 'new'}}
assert s.finish(new)
old.status = 'failed'
old.error = 'stale'
assert not s.finish(old)
assert s.get(record.task_id).result == {{'attempt': 'new'}}
q.enqueue(record.task_id, {{'body': {{'message': 'duplicate'}}, 'request_id': 'audit'}})
def forbidden(*args):
    raise AssertionError('terminal task executed again')
process_message(q, s, q.read(block_ms=1), execute=forbidden)
assert s.get(record.task_id).status == 'succeeded'
assert q.queue_length() == 0
q.client.delete(q.stream)
s.close()
""")
        check("postgresql_fencing_and_duplicate", {"task_id": run_id + "-fence"})

        capacity = json.loads(api_python(f"""
import json, os
from react_agent.server.redis_queue import RedisTaskQueue
os.environ['REACT_AGENT_QUEUE_MAX_TASKS'] = '1'
q = RedisTaskQueue(stream='{run_id}:capacity', group='audit')
q.enqueue('first', {{}})
assert q.queue_length() == 1
try:
    q.enqueue('second', {{}})
except RuntimeError as e:
    assert 'full' in str(e)
else:
    raise AssertionError('limit bypassed')
q.ack(q.read(block_ms=1)[0])
assert q.queue_length() == 0
q.enqueue('third', {{}})
q.ack(q.read(block_ms=1)[0])
q.client.delete(q.stream)
print(json.dumps({{'limit': 1, 'reuse_after_ack': True}}))
"""))
        check("atomic_queue_admission", capacity)

        docker("stop", worker)
        worker_stopped = True
        docker("stop", redis)
        redis_stopped = True
        status, value = request("POST", "/v1/tasks", {"message": "redis outage"})
        assert status == 503 and value["error"]["code"] == "queue_unavailable", value
        docker("start", redis)
        redis_stopped = False
        assert task(task_id, "succeeded")["result"] == completed["result"]
        check("redis_outage_503_and_postgresql_authority", {"status": status, "task_id": task_id})

        key = run_id + ":backup"
        stream = run_id + ":restore"
        assert redis_cli("SET", key, run_id) == "OK"
        redis_cli("XADD", stream, "*", "task_id", "backup-audit")
        config = redis_cli("CONFIG", "GET", "appendonly", "appendfsync", "save", "aof-use-rdb-preamble",
                           "auto-aof-rewrite-percentage", "auto-aof-rewrite-min-size")
        assert "yes" in config and "everysec" in config
        redis_cli("BGREWRITEAOF")
        for _ in range(60):
            info = redis_cli("INFO", "persistence")
            if "aof_rewrite_in_progress:0" in info and "aof_rewrites:0" not in info:
                break
            time.sleep(0.5)
        else:
            raise AssertionError("AOF rewrite did not finish")
        assert "aof_last_bgrewrite_status:ok" in info
        assert redis_cli("SAVE") == "OK"
        docker("restart", redis)
        assert redis_cli("GET", key) == run_id
        assert redis_cli("XLEN", stream) == "1"
        assert task(task_id, "succeeded")["result"] == completed["result"]
        check("redis_rewrite_and_restart", {"config": config, "persistence": info, "task_id": task_id})

        # Snapshot a stopped Redis so the multipart AOF manifest and files are
        # consistent. This copy lives outside its Docker data volume.
        docker("stop", redis)
        redis_stopped = True
        backup = output / "redis-backup"
        backup.mkdir()
        docker("cp", f"{redis}:/data/.", str(backup))
        docker("start", redis)
        redis_stopped = False
        hashes = {str(p.relative_to(backup)): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in backup.rglob("*") if p.is_file()}
        assert "dump.rdb" in hashes and any("manifest" in p for p in hashes)
        for mode in ("rdb", "aof"):
            name = run_id + "-restore-" + mode
            docker("create", "--name", name, "redis:7.4-alpine", "redis-server", "--appendonly",
                   "yes" if mode == "aof" else "no", "--save", "")
            restore_containers.append(name)
            source = str(backup / "dump.rdb") if mode == "rdb" else str(backup) + "/."
            destination = f"{name}:/data/dump.rdb" if mode == "rdb" else f"{name}:/data"
            docker("cp", source, destination)
            docker("start", name)
            value = ""
            for _ in range(30):
                try:
                    value = docker("exec", name, "redis-cli", "--raw", "GET", key)
                    if value == run_id:
                        break
                except RuntimeError:
                    pass
                time.sleep(0.2)
            assert value == run_id
            assert docker("exec", name, "redis-cli", "--raw", "XLEN", stream) == "1"
            check("independent_restore_" + mode, {"backup": str(backup), "sha256": hashes})
        redis_cli("DEL", key, stream)
        docker("start", worker)
        worker_stopped = False
        time.sleep(12)
        assert docker("inspect", worker, "--format", "{{.State.Running}}") == "true"
        logs = docker("logs", worker)
        assert "task_claimed" in logs and "status=running" in logs and "status=succeeded" in logs
        assert "error_category=http_400" in logs
        check("worker_idle_survival_and_event_logs", {"idle_seconds": 12})
        report["status"] = "passed"
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = str(exc)
        raise
    finally:
        if redis_stopped:
            docker("start", redis)
        if worker_stopped:
            docker("start", worker)
        for name in restore_containers:
            # -v removes only the disposable restore container's anonymous volume.
            docker("rm", "-f", "-v", name)
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        (output / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Report: {output / 'report.json'}", flush=True)


if __name__ == "__main__":
    main()
