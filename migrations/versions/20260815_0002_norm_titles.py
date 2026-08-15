"""add norm titles for readable canonical seed

Revision ID: 20260815_0002
Revises: 20260815_0001
"""
from alembic import op
import sqlalchemy as sa

revision = "20260815_0002"
down_revision = "20260815_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("legal_norms", sa.Column("law_name", sa.Text(), nullable=True))
    op.add_column("legal_norms", sa.Column("title", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("legal_norms", "title")
    op.drop_column("legal_norms", "law_name")
