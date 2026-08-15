"""add weighted full-text index for hybrid legal search

Revision ID: 20260815_0004
Revises: 20260815_0003
"""
from alembic import op

revision = "20260815_0004"
down_revision = "20260815_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE legal_norms
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (
            setweight(to_tsvector('russian'::regconfig, coalesce(article_number, '')), 'A') ||
            setweight(to_tsvector('russian'::regconfig, coalesce(code_id, '')), 'A') ||
            setweight(to_tsvector('russian'::regconfig, coalesce(law_name, '')), 'B') ||
            setweight(to_tsvector('russian'::regconfig, coalesce(title, '')), 'B') ||
            setweight(to_tsvector('russian'::regconfig, coalesce(text, '')), 'C')
        ) STORED
        """
    )
    op.execute(
        "CREATE INDEX ix_legal_norms_search_vector ON legal_norms USING GIN (search_vector)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_legal_norms_search_vector")
    op.execute("ALTER TABLE legal_norms DROP COLUMN IF EXISTS search_vector")
