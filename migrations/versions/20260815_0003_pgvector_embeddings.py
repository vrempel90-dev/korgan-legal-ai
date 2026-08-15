"""add pgvector embeddings to legal norms

Revision ID: 20260815_0003
Revises: 20260815_0002
"""
from alembic import op
import sqlalchemy as sa

revision = "20260815_0003"
down_revision = "20260815_0002"
branch_labels = None
depends_on = None

EMBEDDING_DIMENSIONS = 3072


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        f"ALTER TABLE legal_norms ADD COLUMN embedding vector({EMBEDDING_DIMENSIONS}) NULL"
    )
    op.add_column("legal_norms", sa.Column("embedding_model", sa.Text(), nullable=True))
    op.add_column("legal_norms", sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("legal_norms", "embedded_at")
    op.drop_column("legal_norms", "embedding_model")
    op.drop_column("legal_norms", "embedding")
