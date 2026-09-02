"""investigations table

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-02
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "investigations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "merchant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("merchants.id"),
            nullable=False,
        ),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("incident_detected", sa.Boolean(), nullable=False),
        sa.Column("evidence_event_count", sa.Integer(), nullable=False),
        sa.Column(
            "event_type_counts",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("dominant_signal_event_type", sa.String(length=100), nullable=True),
        sa.Column("dominant_signal_share", sa.Numeric(5, 4), nullable=True),
        sa.Column(
            "impact_breakdown",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "impact_amount_unknown_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "evidence",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_investigations_merchant_id", "investigations", ["merchant_id"])
    op.create_index(
        "ix_investigations_merchant_incident",
        "investigations",
        ["merchant_id", "incident_detected"],
    )


def downgrade() -> None:
    op.drop_index("ix_investigations_merchant_incident", table_name="investigations")
    op.drop_index("ix_investigations_merchant_id", table_name="investigations")
    op.drop_table("investigations")
