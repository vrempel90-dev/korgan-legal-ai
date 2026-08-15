"""canonical legal norm corpus with versioning

Revision ID: 20260815_0001
Revises:
Create Date: 2026-08-15
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260815_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "legal_norms",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("code_id", sa.Text(), nullable=False),
        sa.Column("article_number", sa.Text(), nullable=False),
        sa.Column("part", sa.Text(), nullable=False, server_default=""),
        sa.Column("point", sa.Text(), nullable=False, server_default=""),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column(
            "retrieved_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("reviewed_by", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('canonical', 'pending_review')",
            name="ck_legal_norms_status",
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_legal_norms_effective_range",
        ),
        sa.UniqueConstraint(
            "code_id",
            "article_number",
            "part",
            "point",
            "effective_from",
            "source_url",
            name="uq_legal_norms_source_version",
        ),
    )
    op.create_index(
        "ix_legal_norms_lookup",
        "legal_norms",
        ["code_id", "article_number", "part", "point", "status", "effective_from"],
    )


def downgrade() -> None:
    op.drop_index("ix_legal_norms_lookup", table_name="legal_norms")
    op.drop_table("legal_norms")
