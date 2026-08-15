"""isolated pending-review staging for official web fallback

Revision ID: 20260815_0005
Revises: 20260815_0004
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260815_0005"
down_revision = "20260815_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "legal_research_candidates",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("requested_event_date", sa.Date(), nullable=True),
        sa.Column("code_id", sa.Text(), nullable=True),
        sa.Column("law_name", sa.Text(), nullable=True),
        sa.Column("article_number", sa.Text(), nullable=False),
        sa.Column("part", sa.Text(), nullable=False, server_default=""),
        sa.Column("point", sa.Text(), nullable=False, server_default=""),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("proposed_effective_from", sa.Date(), nullable=True),
        sa.Column("proposed_effective_to", sa.Date(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column(
            "retrieved_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending_review"),
        sa.CheckConstraint("status = 'pending_review'", name="ck_research_candidates_pending_only"),
        sa.CheckConstraint(
            "proposed_effective_from IS NULL OR proposed_effective_to IS NULL "
            "OR proposed_effective_to >= proposed_effective_from",
            name="ck_research_candidates_effective_range",
        ),
        sa.UniqueConstraint(
            "source_url",
            "article_number",
            "part",
            "point",
            name="uq_research_candidates_source_locator",
        ),
    )
    op.create_index(
        "ix_research_candidates_pending_locator",
        "legal_research_candidates",
        ["status", "article_number", "part", "point"],
    )


def downgrade() -> None:
    op.drop_index("ix_research_candidates_pending_locator", table_name="legal_research_candidates")
    op.drop_table("legal_research_candidates")
