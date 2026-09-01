from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest


pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")


def _chat_handler(body: dict, request_id: str):
    if body.get("message") == "fail":
        raise RuntimeError("injected worker failure")
    return 200, {"answer": body.get("message") or body.get("query"), "request_id": request_id}


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def _wait_for_terminal(client, task_id: str) -> dict:
    for _ in range(100):
        payload = (await client.get(f"/v1/tasks/{task_id}")).json()
        if payload["status"] in {"succeeded", "failed", "cancelled"}:
            return payload
        await asyncio.sleep(0.01)
    raise AssertionError("task did not reach a terminal state")


@pytest.mark.anyio
async def test_fastapi_contract_and_durable_task_state(tmp_path):
    from react_agent.server.fastapi_app import create_app
    from react_agent.server.sqlalchemy_store import SQLAlchemyTaskStore
    from react_agent.server.task_manager import TaskManager

    url = f"sqlite:///{tmp_path / 'tasks.db'}"
    store = SQLAlchemyTaskStore(url)
    manager = TaskManager(max_workers=1, store=store)
    api = create_app(manager=manager, chat_handler=_chat_handler, initialize_runtime=False)

    try:
        transport = httpx.ASGITransport(app=api)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            health = await client.get(
                "/v1/health", headers={"X-Request-Id": "health-1"}
            )
            assert health.status_code == 200
            assert health.json()["request_id"] == "health-1"

            invalid = await client.post("/v1/tasks", json={})
            assert invalid.status_code == 422

            oversized = await client.post("/v1/tasks", json={"message": "x" * 100_001})
            assert oversized.status_code == 422

            missing = await client.get("/v1/tasks/missing")
            assert missing.status_code == 404
            assert missing.json()["error"]["code"] == "not_found"

            schema = (await client.get("/openapi.json")).json()
            assert schema["paths"]["/v1/tasks"]["post"]["responses"]["202"]

            created = await client.post(
                "/v1/tasks",
                json={"message": "hello"},
                headers={"X-Request-Id": "request-1"},
            )
            assert created.status_code == 202
            assert created.json()["request_id"] == "request-1"

            completed = await _wait_for_terminal(client, created.json()["task_id"])
            assert completed["status"] == "succeeded"
            assert completed["result"]["payload"]["answer"] == "hello"

            restored_store = SQLAlchemyTaskStore(url)
            try:
                restored = restored_store.get(created.json()["task_id"])
                assert restored is not None
                assert restored.status == "succeeded"
            finally:
                restored_store.close()
    finally:
        manager.shutdown()
        store.close()


def test_alembic_upgrades_an_empty_database(tmp_path):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect

    project_root = Path(__file__).resolve().parents[1]
    config = Config(project_root / "alembic.ini")
    config.set_main_option("script_location", str(project_root / "migrations"))
    database_url = f"sqlite:///{tmp_path / 'migrated.db'}"
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "head")

    engine = create_engine(database_url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert "react_agent_tasks" in tables
        assert "security_triage_cases" in tables
        assert "security_triage_review_events" in tables
    finally:
        engine.dispose()

    command.downgrade(config, "base")

    engine = create_engine(database_url)
    try:
        assert "react_agent_tasks" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()


@pytest.mark.anyio
async def test_worker_failure_is_queryable(tmp_path):
    from react_agent.server.fastapi_app import create_app
    from react_agent.server.sqlalchemy_store import SQLAlchemyTaskStore
    from react_agent.server.task_manager import TaskManager

    store = SQLAlchemyTaskStore(f"sqlite:///{tmp_path / 'failures.db'}")
    manager = TaskManager(max_workers=1, store=store)
    api = create_app(manager=manager, chat_handler=_chat_handler, initialize_runtime=False)
    try:
        transport = httpx.ASGITransport(app=api)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created = (await client.post("/v1/tasks", json={"message": "fail"})).json()
            failed = await _wait_for_terminal(client, created["task_id"])
            assert failed["status"] == "failed"
            assert failed["error"] == "injected worker failure"
    finally:
        manager.shutdown()
        store.close()
