"""financial_events table

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-01
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "financial_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "merchant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("merchants.id"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("external_reference", sa.String(length=255), nullable=True),
        sa.Column("amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("status", sa.String(length=100), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "source",
            "external_reference",
            name="uq_financial_events_source_external_reference",
        ),
    )
    op.create_index("ix_financial_events_merchant_id", "financial_events", ["merchant_id"])
    op.create_index("ix_financial_events_event_type", "financial_events", ["event_type"])
    op.create_index(
        "ix_financial_events_merchant_type_occurred",
        "financial_events",
        ["merchant_id", "event_type", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_financial_events_merchant_type_occurred", table_name="financial_events")
    op.drop_index("ix_financial_events_event_type", table_name="financial_events")
    op.drop_index("ix_financial_events_merchant_id", table_name="financial_events")
    op.drop_table("financial_events")
