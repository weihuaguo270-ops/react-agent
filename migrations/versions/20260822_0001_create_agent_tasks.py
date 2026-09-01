"""create durable agent task table

Revision ID: 20260822_0001
Revises:
Create Date: 2026-08-22
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260822_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "react_agent_tasks",
        sa.Column("task_id", sa.String(length=64), primary_key=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("started_at", sa.Float(), nullable=True),
        sa.Column("finished_at", sa.Float(), nullable=True),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error_text", sa.String(length=1000), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("react_agent_tasks")
