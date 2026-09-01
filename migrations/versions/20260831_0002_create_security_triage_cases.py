"""create security triage cases and review events

Revision ID: 20260831_0002
Revises: 20260822_0001
Create Date: 2026-08-31
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260831_0002"
down_revision = "20260822_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "security_triage_cases",
        sa.Column("case_id", sa.String(length=64), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("case_json", sa.Text(), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=False),
    )
    op.create_table(
        "security_triage_review_events",
        sa.Column("review_id", sa.String(length=64), primary_key=True),
        sa.Column(
            "case_id",
            sa.String(length=64),
            sa.ForeignKey("security_triage_cases.case_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("case_version", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("reviewer", sa.String(length=200), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
    )
    op.create_index(
        "ix_security_triage_review_events_case_id",
        "security_triage_review_events",
        ["case_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_security_triage_review_events_case_id",
        table_name="security_triage_review_events",
    )
    op.drop_table("security_triage_review_events")
    op.drop_table("security_triage_cases")
