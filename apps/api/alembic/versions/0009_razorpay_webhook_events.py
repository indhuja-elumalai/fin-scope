"""razorpay_webhook_events table

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-03
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "razorpay_webhook_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("razorpay_event_id", sa.String(length=255), nullable=False),
        sa.Column("razorpay_event_type", sa.String(length=100), nullable=False),
        sa.Column("outcome", sa.String(length=40), nullable=False),
        sa.Column("financial_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "raw_payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    # The idempotency anchor: at most one ledger row per Razorpay event id.
    # See app.models.razorpay_webhook_event module docstring.
    op.create_unique_constraint(
        "uq_razorpay_webhook_events_event_id",
        "razorpay_webhook_events",
        ["razorpay_event_id"],
    )
    op.create_index(
        "ix_razorpay_webhook_events_event_type",
        "razorpay_webhook_events",
        ["razorpay_event_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_razorpay_webhook_events_event_type", table_name="razorpay_webhook_events")
    op.drop_constraint(
        "uq_razorpay_webhook_events_event_id",
        "razorpay_webhook_events",
        type_="unique",
    )
    op.drop_table("razorpay_webhook_events")
