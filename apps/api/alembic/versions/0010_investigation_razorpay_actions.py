"""investigation_razorpay_actions table

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-03
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "investigation_razorpay_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "investigation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("investigations.id"),
            nullable=False,
        ),
        sa.Column(
            "decision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("investigation_decisions.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("rejection_reason", sa.String(length=500), nullable=True),
        sa.Column("scenario", sa.String(length=100), nullable=True),
        sa.Column("simulation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("policy_decision_snapshot", sa.String(length=30), nullable=True),
        sa.Column("razorpay_order_id", sa.String(length=255), nullable=True),
        sa.Column("razorpay_receipt", sa.String(length=40), nullable=True),
        sa.Column("executor_version", sa.String(length=20), nullable=False),
        sa.Column(
            "raw_response",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    # The idempotency anchor: at most one real Razorpay action row per
    # decision. See app.models.investigation_razorpay_action module
    # docstring.
    op.create_unique_constraint(
        "uq_investigation_razorpay_actions_decision_id",
        "investigation_razorpay_actions",
        ["decision_id"],
    )
    op.create_index(
        "ix_investigation_razorpay_actions_investigation_id",
        "investigation_razorpay_actions",
        ["investigation_id"],
    )
    op.create_index(
        "ix_investigation_razorpay_actions_investigation_created",
        "investigation_razorpay_actions",
        ["investigation_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_investigation_razorpay_actions_investigation_created",
        table_name="investigation_razorpay_actions",
    )
    op.drop_index(
        "ix_investigation_razorpay_actions_investigation_id",
        table_name="investigation_razorpay_actions",
    )
    op.drop_constraint(
        "uq_investigation_razorpay_actions_decision_id",
        "investigation_razorpay_actions",
        type_="unique",
    )
    op.drop_table("investigation_razorpay_actions")
