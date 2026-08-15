"""add explicit lawyer review decisions for fallback candidates

Revision ID: 20260815_0006
Revises: 20260815_0005
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260815_0006"
down_revision = "20260815_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_research_candidates_pending_only",
        "legal_research_candidates",
        type_="check",
    )
    op.add_column("legal_research_candidates", sa.Column("reviewed_by", sa.Text(), nullable=True))
    op.add_column(
        "legal_research_candidates",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("legal_research_candidates", sa.Column("review_note", sa.Text(), nullable=True))
    op.add_column(
        "legal_research_candidates",
        sa.Column("canonical_norm_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_research_candidates_canonical_norm",
        "legal_research_candidates",
        "legal_norms",
        ["canonical_norm_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_research_candidates_status",
        "legal_research_candidates",
        "status IN ('pending_review', 'approved', 'rejected')",
    )
    op.create_check_constraint(
        "ck_research_candidates_review_metadata",
        "legal_research_candidates",
        "(status = 'pending_review' AND reviewed_by IS NULL AND reviewed_at IS NULL "
        "AND canonical_norm_id IS NULL) OR "
        "(status = 'approved' AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL "
        "AND canonical_norm_id IS NOT NULL) OR "
        "(status = 'rejected' AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL "
        "AND canonical_norm_id IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_research_candidates_review_metadata",
        "legal_research_candidates",
        type_="check",
    )
    op.drop_constraint(
        "ck_research_candidates_status",
        "legal_research_candidates",
        type_="check",
    )
    op.drop_constraint(
        "fk_research_candidates_canonical_norm",
        "legal_research_candidates",
        type_="foreignkey",
    )
    op.drop_column("legal_research_candidates", "canonical_norm_id")
    op.drop_column("legal_research_candidates", "review_note")
    op.drop_column("legal_research_candidates", "reviewed_at")
    op.drop_column("legal_research_candidates", "reviewed_by")
    op.create_check_constraint(
        "ck_research_candidates_pending_only",
        "legal_research_candidates",
        "status = 'pending_review'",
    )
