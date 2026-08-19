"""LangGraph checkpointer factory."""
from __future__ import annotations

import os

from langgraph.checkpoint.memory import MemorySaver


def build_checkpointer():
    backend = os.environ.get("LANGGRAPH_CHECKPOINT_BACKEND", "memory").strip().lower()
    if backend == "memory":
        return MemorySaver()
    if backend == "mysql":
        from mysql_checkpoint import MySQLCheckpointSaver

        return MySQLCheckpointSaver()
    raise ValueError(f"unsupported LANGGRAPH_CHECKPOINT_BACKEND: {backend}")
