"""Live MySQL persistence checks.

These tests are opt-in because they create tables and briefly insert rows into the
configured database. They clean up only the rows created by the current test run.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import quote

import pytest


pytestmark = pytest.mark.mysql_live


def _mysql_url() -> str:
    pytest.importorskip("pymysql")
    url = (
        os.environ.get("REACT_AGENT_MYSQL_URL")
        or os.environ.get("LANGGRAPH_MYSQL_URL")
        or os.environ.get("MYSQL_URL")
    )
    if not url:
        if os.environ.get("MYSQL_HOST") and os.environ.get("MYSQL_DATABASE"):
            user = quote(os.environ.get("MYSQL_USER", "root"), safe="")
            password = quote(os.environ.get("MYSQL_PASSWORD", ""), safe="")
            url = "mysql://{0}:{1}@{2}:{3}/{4}".format(
                user,
                password,
                os.environ["MYSQL_HOST"],
                os.environ.get("MYSQL_PORT", "3306"),
                os.environ["MYSQL_DATABASE"],
            )
        else:
            pytest.skip(
                "set a MySQL URL or MYSQL_HOST + MYSQL_DATABASE (and optional credentials)"
            )
    return url


def _load_mysql_saver():
    pytest.importorskip("langgraph")
    path = (
        Path(__file__).resolve().parents[1]
        / "experiments"
        / "langgraph"
        / "graph"
        / "mysql_checkpoint.py"
    )
    spec = importlib.util.spec_from_file_location("react_agent_mysql_checkpoint", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.MySQLCheckpointSaver


def test_task_status_survives_store_recreation():
    from react_agent.server.task_manager import MySQLTaskStore, TaskRecord

    store = MySQLTaskStore(_mysql_url())
    task_id = f"live-{uuid.uuid4().hex}"
    expected = TaskRecord(
        task_id=task_id,
        status="succeeded",
        result={"restored": True},
        finished_at=time.time(),
    )
    try:
        store.save(expected)
        restored = MySQLTaskStore(_mysql_url()).get(task_id)
        assert restored is not None
        assert restored.status == "succeeded"
        assert restored.result == {"restored": True}
    finally:
        with store._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM react_agent_tasks WHERE task_id=%s", (task_id,))


def test_checkpoint_and_pending_writes_survive_saver_recreation():
    from langgraph.checkpoint.base import empty_checkpoint

    Saver = _load_mysql_saver()
    url = _mysql_url()
    saver = Saver(url)
    thread_id = f"live-{uuid.uuid4().hex}"
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    checkpoint = empty_checkpoint()
    saved_config = saver.put(config, checkpoint, {"source": "mysql-live"}, {})
    saver.put_writes(saved_config, [("result", {"restored": True})], "task-1")

    try:
        restored = Saver(url).get_tuple(saved_config)
        assert restored is not None
        assert restored.checkpoint["id"] == checkpoint["id"]
        assert restored.metadata["source"] == "mysql-live"
        assert restored.pending_writes == [("task-1", "result", {"restored": True})]
    finally:
        with saver._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM langgraph_writes WHERE thread_id=%s", (thread_id,))
                cursor.execute("DELETE FROM langgraph_checkpoints WHERE thread_id=%s", (thread_id,))
