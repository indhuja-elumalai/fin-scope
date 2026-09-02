"""investigation_simulations table

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-02
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "investigation_simulations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "investigation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("investigations.id"),
            nullable=False,
        ),
        sa.Column("scenario", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("simulator_version", sa.String(length=20), nullable=False),
        sa.Column(
            "input_snapshot",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "assumptions",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "result",
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
        "ix_investigation_simulations_investigation_id",
        "investigation_simulations",
        ["investigation_id"],
    )
    # Supports "simulation history for this investigation, newest first"
    # without a table scan -- same shape as
    # ix_investigation_reasoning_investigation_created in 0004, one
    # composite index for the one query this table actually needs.
    op.create_index(
        "ix_investigation_simulations_investigation_created",
        "investigation_simulations",
        ["investigation_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_investigation_simulations_investigation_created",
        table_name="investigation_simulations",
    )
    op.drop_index(
        "ix_investigation_simulations_investigation_id",
        table_name="investigation_simulations",
    )
    op.drop_table("investigation_simulations")
