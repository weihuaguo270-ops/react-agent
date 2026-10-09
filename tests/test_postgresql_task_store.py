from react_agent.server.sqlalchemy_store import PostgreSQLTaskStore
from react_agent.server.task_manager import TaskRecord


def test_postgresql_store_contract_with_sqlite(tmp_path):
    store = PostgreSQLTaskStore(f"sqlite:///{tmp_path / 'tasks.sqlite'}")
    try:
        record = TaskRecord("task-1", status="queued", result={"answer": "ok"})
        store.save(record)

        record.status = "succeeded"
        record.error = None
        store.save(record)

        loaded = store.get("task-1")
        assert loaded is not None
        assert loaded.status == "succeeded"
        assert loaded.result == {"answer": "ok"}
        assert store.get("missing") is None
    finally:
        store.close()


def test_stale_attempt_and_terminal_updates_are_rejected(tmp_path):
    store = PostgreSQLTaskStore(f"sqlite:///{tmp_path / 'fenced.sqlite'}")
    try:
        store.save(TaskRecord("task-fenced"))
        old = store.claim("task-fenced", now=100, visibility_seconds=10)
        assert old is not None
        assert store.claim("task-fenced", now=105, visibility_seconds=10) is None
        new = store.claim("task-fenced", now=111, visibility_seconds=10)
        assert new is not None
        old.status = "succeeded"
        old.result = {"attempt": "old"}
        assert store.finish(old) is False
        new.status = "succeeded"
        new.result = {"attempt": "new"}
        assert store.finish(new) is True
        store.save(TaskRecord("task-fenced", status="running", started_at=100))
        assert store.get("task-fenced").result == {"attempt": "new"}
        assert store.cancel("task-fenced").status == "succeeded"
        assert store.claim("task-fenced", now=999, visibility_seconds=10) is None
    finally:
        store.close()


def test_cancel_wins_over_a_running_attempt(tmp_path):
    store = PostgreSQLTaskStore(f"sqlite:///{tmp_path / 'cancel.sqlite'}")
    try:
        store.save(TaskRecord("task-cancel"))
        running = store.claim("task-cancel", now=100, visibility_seconds=10)
        assert store.cancel("task-cancel").status == "cancelled"
        running.status = "failed"
        running.error = "late failure"
        assert store.finish(running) is False
        assert store.get("task-cancel").status == "cancelled"
    finally:
        store.close()
