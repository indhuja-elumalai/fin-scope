"""investigation_razorpay_verifications table

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-03
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "investigation_razorpay_verifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "investigation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("investigations.id"),
            nullable=False,
        ),
        sa.Column(
            "razorpay_action_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("investigation_razorpay_actions.id"),
            nullable=False,
        ),
        sa.Column(
            "decision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("investigation_decisions.id"),
            nullable=True,
        ),
        sa.Column("simulation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("verifier_version", sa.String(length=20), nullable=False),
        sa.Column(
            "expected_snapshot",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "observed_snapshot",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "comparison",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "evidence",
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
    )
    # The idempotency anchor: at most one razorpay verification row per
    # razorpay action. See
    # app.models.investigation_razorpay_verification module docstring.
    op.create_unique_constraint(
        "uq_investigation_razorpay_verifications_razorpay_action_id",
        "investigation_razorpay_verifications",
        ["razorpay_action_id"],
    )
    op.create_index(
        "ix_investigation_razorpay_verifications_investigation_id",
        "investigation_razorpay_verifications",
        ["investigation_id"],
    )
    # Supports "razorpay verification history for this investigation,
    # newest first" without a table scan -- same shape as
    # ix_investigation_outcome_verifications_investigation_created in
    # 0008 / ix_investigation_razorpay_actions_investigation_created in
    # 0010.
    op.create_index(
        "ix_investigation_razorpay_verifications_investigation_created",
        "investigation_razorpay_verifications",
        ["investigation_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_investigation_razorpay_verifications_investigation_created",
        table_name="investigation_razorpay_verifications",
    )
    op.drop_index(
        "ix_investigation_razorpay_verifications_investigation_id",
        table_name="investigation_razorpay_verifications",
    )
    op.drop_constraint(
        "uq_investigation_razorpay_verifications_razorpay_action_id",
        "investigation_razorpay_verifications",
        type_="unique",
    )
    op.drop_table("investigation_razorpay_verifications")
