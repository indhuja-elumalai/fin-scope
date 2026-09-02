"""investigation_decisions table

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-02
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "investigation_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "investigation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("investigations.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("evaluation_version", sa.String(length=20), nullable=False),
        sa.Column("policy_version", sa.String(length=20), nullable=True),
        sa.Column(
            "candidate_simulation_ids",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "evaluation_result",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("policy_decision", sa.String(length=30), nullable=True),
        sa.Column(
            "policy_reasons",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "input_snapshot",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("failure_reason", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_investigation_decisions_investigation_id",
        "investigation_decisions",
        ["investigation_id"],
    )
    # Supports "decision history for this investigation, newest first"
    # without a table scan -- same shape as
    # ix_investigation_simulations_investigation_created in 0005.
    op.create_index(
        "ix_investigation_decisions_investigation_created",
        "investigation_decisions",
        ["investigation_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_investigation_decisions_investigation_created",
        table_name="investigation_decisions",
    )
    op.drop_index(
        "ix_investigation_decisions_investigation_id",
        table_name="investigation_decisions",
    )
    op.drop_table("investigation_decisions")
