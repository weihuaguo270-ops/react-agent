import pytest

from react_agent.server.redis_task_manager import RedisTaskManager
from react_agent.server.task_manager import TaskRecord
from react_agent.worker import process_message


class FakeStore:
    def __init__(self):
        self.records = {}

    def save(self, record):
        self.records[record.task_id] = TaskRecord(
            task_id=record.task_id,
            status=record.status,
            created_at=record.created_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
            result=record.result,
            error=record.error,
        )

    def get(self, task_id):
        from dataclasses import replace

        record = self.records.get(task_id)
        return replace(record) if record is not None else None

    def claim(self, task_id, *, now, visibility_seconds):
        record = self.get(task_id)
        if record.status == "queued" or (record.status == "running" and record.started_at <= now - visibility_seconds):
            record.status = "running"
            record.started_at = now
            self.save(record)
            return record
        return None

    def finish(self, record):
        current = self.get(record.task_id)
        if current.status == "running" and current.started_at == record.started_at:
            self.save(record)
            return True
        return False

    def cancel(self, task_id):
        record = self.get(task_id)
        record.status = "cancelled"
        self.save(record)
        return record


class FakeQueue:
    def __init__(self):
        self.messages = []
        self.acks = []
        self.cancelled = set()

    def queue_length(self):
        return len(self.messages)

    def ensure_group(self):
        pass

    def enqueue(self, task_id, payload):
        self.messages.append(("1-0", task_id, payload))
        return "1-0"

    def request_cancel(self, task_id):
        self.cancelled.add(task_id)

    def is_cancelled(self, task_id):
        return task_id in self.cancelled

    def ack(self, message_id):
        self.acks.append(message_id)

    def close(self):
        pass


def test_redis_manager_persists_then_enqueues():
    store = FakeStore()
    queue = FakeQueue()
    manager = RedisTaskManager(store=store, queue=queue)

    record = manager.submit_payload({"message": "hello"}, "req-1")

    assert record.status == "queued"
    assert store.get(record.task_id).status == "queued"
    assert queue.messages[0][1] == record.task_id
    assert queue.messages[0][2]["request_id"] == "req-1"


def test_worker_completes_task_and_acknowledges_message():
    store = FakeStore()
    queue = FakeQueue()
    manager = RedisTaskManager(store=store, queue=queue)
    record = manager.submit_payload({"message": "hello"}, "req-1")
    message = queue.messages.pop(0)

    process_message(
        queue,
        store,
        message,
        execute=lambda body, request_id: (200, {"answer": body["message"], "request_id": request_id}),
    )

    completed = store.get(record.task_id)
    assert completed.status == "succeeded"
    assert completed.result["payload"]["answer"] == "hello"
    assert queue.acks == ["1-0"]


def test_cancelled_task_is_not_executed():
    store = FakeStore()
    queue = FakeQueue()
    manager = RedisTaskManager(store=store, queue=queue)
    record = manager.submit_payload({"message": "hello"}, "req-1")
    manager.cancel(record.task_id)
    message = queue.messages.pop(0)
    called = []

    process_message(queue, store, message, execute=lambda *_: called.append(True))

    assert called == []
    assert store.get(record.task_id).status == "cancelled"


def test_duplicate_delivery_does_not_execute_terminal_task():
    store = FakeStore()
    queue = FakeQueue()
    manager = RedisTaskManager(store=store, queue=queue)
    record = manager.submit_payload({"message": "hello"}, "req-1")
    message = queue.messages.pop(0)
    process_message(
        queue,
        store,
        message,
        execute=lambda body, request_id: (200, {"answer": body["message"]}),
    )
    called = []
    process_message(queue, store, message, execute=lambda *_: called.append(True))
    assert called == []
    assert store.get(record.task_id).status == "succeeded"


def test_worker_persists_http_failure_as_failed():
    store = FakeStore()
    queue = FakeQueue()
    manager = RedisTaskManager(store=store, queue=queue)
    record = manager.submit_payload({"message": "hello"}, "req-1")
    message = queue.messages.pop(0)
    process_message(
        queue,
        store,
        message,
        execute=lambda *_: (503, {"error": {"code": "upstream_unavailable"}}),
    )
    failed = store.get(record.task_id)
    assert failed.status == "failed"
    assert "upstream_unavailable" in failed.error


def test_database_failure_leaves_delivery_pending():
    class UnavailableStore(FakeStore):
        def finish(self, record):
            raise ConnectionError("database unavailable")

    store = UnavailableStore()
    queue = FakeQueue()
    record = RedisTaskManager(store=store, queue=queue).submit_payload({"message": "hello"}, "req-1")
    with pytest.raises(ConnectionError):
        process_message(queue, store, queue.messages[0], execute=lambda *_: (200, {"answer": "ok"}))
    assert queue.acks == []
    assert store.get(record.task_id).status == "running"


def test_cancel_during_execution_preserves_cancelled_state():
    store = FakeStore()
    queue = FakeQueue()
    manager = RedisTaskManager(store=store, queue=queue)
    record = manager.submit_payload({"message": "hello"}, "req-1")

    def execute(*_):
        manager.cancel(record.task_id)
        raise ValueError("execution failed after cancellation")

    process_message(queue, store, queue.messages[0], execute=execute)
    assert store.get(record.task_id).status == "cancelled"
    assert queue.acks == ["1-0"]


def test_live_duplicate_is_not_executed_or_acknowledged():
    store = FakeStore()
    queue = FakeQueue()
    manager = RedisTaskManager(store=store, queue=queue)
    record = manager.submit_payload({"message": "hello"}, "req-1")
    import time

    store.claim(record.task_id, now=time.time(), visibility_seconds=900)
    called = []
    process_message(queue, store, queue.messages[0], execute=lambda *_: called.append(True))
    assert called == []
    assert queue.acks == []


@pytest.mark.parametrize("full", [False, True])
def test_task_api_maps_queue_errors(monkeypatch, full):
    from fastapi.testclient import TestClient
    from react_agent.server.fastapi_app import create_app

    class BrokenQueue(FakeQueue):
        def queue_length(self):
            if full:
                return 10000
            raise ConnectionError("redis unavailable")

    monkeypatch.delenv("REACT_AGENT_AUTH_TOKEN", raising=False)
    manager = RedisTaskManager(store=FakeStore(), queue=BrokenQueue())
    with TestClient(create_app(manager=manager, initialize_runtime=False), base_url="http://127.0.0.1") as client:
        response = client.post("/v1/tasks", json={"message": "hello"})
    assert response.status_code == (429 if full else 503)
    assert response.json()["error"]["code"] == ("queue_full" if full else "queue_unavailable")
