"""investigation_outcome_verifications table

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-03
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "investigation_outcome_verifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "investigation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("investigations.id"),
            nullable=False,
        ),
        sa.Column(
            "action_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("investigation_actions.id"),
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
    # The idempotency anchor: at most one verification row per action. See
    # app.models.investigation_outcome_verification module docstring.
    op.create_unique_constraint(
        "uq_investigation_outcome_verifications_action_id",
        "investigation_outcome_verifications",
        ["action_id"],
    )
    op.create_index(
        "ix_investigation_outcome_verifications_investigation_id",
        "investigation_outcome_verifications",
        ["investigation_id"],
    )
    # Supports "verification history for this investigation, newest first"
    # without a table scan -- same shape as
    # ix_investigation_actions_investigation_created in 0007.
    op.create_index(
        "ix_investigation_outcome_verifications_investigation_created",
        "investigation_outcome_verifications",
        ["investigation_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_investigation_outcome_verifications_investigation_created",
        table_name="investigation_outcome_verifications",
    )
    op.drop_index(
        "ix_investigation_outcome_verifications_investigation_id",
        table_name="investigation_outcome_verifications",
    )
    op.drop_constraint(
        "uq_investigation_outcome_verifications_action_id",
        "investigation_outcome_verifications",
        type_="unique",
    )
    op.drop_table("investigation_outcome_verifications")
