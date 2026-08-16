"""add curation fields: applicable document types and planned re-verification date

Revision ID: 20260815_0012
Revises: 20260815_0011

``reviewed_by`` / ``reviewed_at`` already record who verified a norm and when, so no separate
verified_by/verified_at pair is introduced: one provenance mechanism, not two.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260815_0012"
down_revision = "20260815_0011"
branch_labels = None
depends_on = None

# Six months is the default cadence for re-checking that a norm is still in force in the wording
# the corpus holds. It is a default, not a rule: a volatile area can be given a shorter one.
DEFAULT_REVIEW_MONTHS = 6


def upgrade() -> None:
    op.add_column(
        "legal_norms",
        sa.Column(
            "applicable_document_types",
            sa.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
    )
    op.add_column("legal_norms", sa.Column("next_review_date", sa.Date(), nullable=True))
    # Existing reviewed rows get a cadence starting from when they were actually reviewed, so the
    # first re-verification wave is spread the way the original review was.
    op.execute(
        f"""
        UPDATE legal_norms
        SET next_review_date = (
            COALESCE(reviewed_at::date, effective_from) + INTERVAL '{DEFAULT_REVIEW_MONTHS} months'
        )::date
        WHERE next_review_date IS NULL
        """
    )
    op.create_index(
        "ix_legal_norms_next_review",
        "legal_norms",
        ["next_review_date", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_legal_norms_next_review", table_name="legal_norms")
    op.drop_column("legal_norms", "next_review_date")
    op.drop_column("legal_norms", "applicable_document_types")
