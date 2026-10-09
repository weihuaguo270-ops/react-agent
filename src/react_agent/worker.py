"""Redis task worker entry point for the MVP deployment."""
from __future__ import annotations

import argparse
import logging
import os
import time
from typing import Any, Callable

from react_agent.server.chat_router import handle_chat
from react_agent.server.redis_queue import RedisTaskQueue
from react_agent.server.sqlalchemy_store import PostgreSQLTaskStore


logger = logging.getLogger(__name__)


def execute_chat(body: dict[str, Any], request_id: str) -> tuple[int, dict[str, Any]]:
    """Execute the same request-level permission context as the HTTP path."""
    from react_agent.safety.permission_gate import set_approval_credential, set_request_id
    from react_agent.server.health import capture_approval_status

    set_request_id(request_id)
    set_approval_credential(str(body.get("approval_id") or "").strip())
    status, payload = handle_chat(body, request_id)
    if "request_id" not in payload and "error" not in payload:
        payload["request_id"] = request_id
    approval_id = capture_approval_status(payload)
    if approval_id:
        payload["status"] = "awaiting_approval"
        payload["approval_id"] = approval_id
    return status, payload


def process_message(
    queue: RedisTaskQueue,
    store: PostgreSQLTaskStore,
    message: tuple[str, str, dict[str, Any]],
    *,
    execute: Callable[[dict[str, Any], str], tuple[int, dict[str, Any]]] = execute_chat,
) -> None:
    message_id, task_id, payload = message
    logger.info("task_claimed task_id=%s message_id=%s", task_id, message_id)
    record = store.get(task_id)
    if record is None or record.status in {"succeeded", "failed", "cancelled"}:
        logger.info("task_duplicate_ignored task_id=%s", task_id)
        queue.ack(message_id)
        return
    if queue.is_cancelled(task_id):
        store.cancel(task_id)
        queue.ack(message_id)
        return
    record = store.claim(
        task_id, now=time.time(),
        visibility_seconds=int(os.environ.get("REACT_AGENT_QUEUE_VISIBILITY_MS", "900000")) / 1000,
    )
    if record is None:
        # Another live attempt owns it. Keep pending for recovery instead of
        # acknowledging work that has not durably finished.
        return
    logger.info("task_state task_id=%s status=running", task_id)
    try:
        status, result = execute(payload["body"], str(payload["request_id"]))
        record.finished_at = time.time()
        if queue.is_cancelled(task_id):
            record.status = "cancelled"
            logger.info("task_state task_id=%s status=cancelled", task_id)
        elif status >= 400 or "error" in result:
            record.status = "failed"
            error = result.get("error") if isinstance(result, dict) else result
            record.error = str(error)[:500]
            logger.info("task_state task_id=%s status=failed error_category=http_%s", task_id, status)
        else:
            record.status = "succeeded"
            record.result = {"http_status": status, "payload": result}
            logger.info("task_state task_id=%s status=succeeded", task_id)
    except Exception as exc:
        record.status = "failed"
        record.error = str(exc)[:500]
        record.finished_at = time.time()
        logger.error("task_state task_id=%s status=failed error_category=%s", task_id, type(exc).__name__)
    # Persist before acknowledgement. Database/network errors escape to the
    # worker loop, leaving the delivery pending for another attempt.
    if store.finish(record):
        queue.ack(message_id)
    else:
        latest = store.get(task_id)
        if latest is not None and latest.status in {"succeeded", "failed", "cancelled"}:
            queue.ack(message_id)
        logger.info("task_stale_result_ignored task_id=%s", task_id)


def run_worker(*, once: bool = False, queue: RedisTaskQueue | None = None, store: Any | None = None) -> None:
    queue = queue or RedisTaskQueue()
    store = store or PostgreSQLTaskStore()
    try:
        while True:
            try:
                queue.ensure_group()
                message = queue.claim_pending() or queue.read()
                if message is not None:
                    process_message(queue, store, message)
            except Exception as exc:
                logger.error("worker_retry error_category=%s", type(exc).__name__)
                if once:
                    raise
                time.sleep(1)
                continue
            if message is None:
                if once:
                    return
                continue
            if once:
                return
    finally:
        close = getattr(store, "close", None)
        if close:
            close()
        queue.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="react-agent Redis task worker")
    parser.add_argument("--once", action="store_true", help="process one task and exit")
    args = parser.parse_args()
    run_worker(once=args.once)
