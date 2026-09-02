"""investigation_reasoning table

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-02
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "investigation_reasoning",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "investigation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("investigations.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column(
            "hypotheses",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
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
        "ix_investigation_reasoning_investigation_id",
        "investigation_reasoning",
        ["investigation_id"],
    )
    # Supports "latest reasoning result for this investigation" without a
    # table scan -- the same shape as ix_investigations_merchant_incident in
    # 0003, one composite index for the one query this table actually needs.
    op.create_index(
        "ix_investigation_reasoning_investigation_created",
        "investigation_reasoning",
        ["investigation_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_investigation_reasoning_investigation_created",
        table_name="investigation_reasoning",
    )
    op.drop_index(
        "ix_investigation_reasoning_investigation_id",
        table_name="investigation_reasoning",
    )
    op.drop_table("investigation_reasoning")
