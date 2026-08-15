"""add the judicial-practice corpus with hybrid retrieval columns

Revision ID: 20260815_0011
Revises: 20260815_0010
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260815_0011"
down_revision = "20260815_0010"
branch_labels = None
depends_on = None

EMBEDDING_DIMENSIONS = 3072


def upgrade() -> None:
    op.create_table(
        "judicial_practice",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("case_number", sa.Text(), nullable=False),
        sa.Column("court_name", sa.Text(), nullable=False),
        sa.Column("decided_on", sa.Date(), nullable=False),
        sa.Column("instance", sa.Text(), nullable=False),
        sa.Column("legal_area", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("text_excerpt", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("cited_articles", sa.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column(
            "retrieved_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        # An act is invisible to retrieval until a human marks it canonical, mirroring the rule the
        # legislation corpus already follows.
        sa.Column("status", sa.Text(), nullable=False, server_default="pending_review"),
        sa.Column("reviewed_by", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("embedding_model", sa.Text(), nullable=True),
        sa.Column("embedded_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.UniqueConstraint("case_number", "source_url", name="uq_judicial_practice_identity"),
        sa.CheckConstraint(
            "status IN ('canonical','pending_review')",
            name="ck_judicial_practice_status",
        ),
    )
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        f"ALTER TABLE judicial_practice ADD COLUMN embedding vector({EMBEDDING_DIMENSIONS}) NULL"
    )
    op.execute(
        """
        ALTER TABLE judicial_practice
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (
            setweight(to_tsvector('russian'::regconfig, coalesce(case_number, '')), 'A') ||
            setweight(to_tsvector('russian'::regconfig, coalesce(summary, '')), 'B') ||
            setweight(to_tsvector('russian'::regconfig, coalesce(text_excerpt, '')), 'C')
        ) STORED
        """
    )
    op.execute(
        "CREATE INDEX ix_judicial_practice_search_vector "
        "ON judicial_practice USING GIN (search_vector)"
    )
    op.create_index(
        "ix_judicial_practice_area",
        "judicial_practice",
        ["legal_area", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_judicial_practice_area", table_name="judicial_practice")
    op.execute("DROP INDEX IF EXISTS ix_judicial_practice_search_vector")
    op.drop_table("judicial_practice")
