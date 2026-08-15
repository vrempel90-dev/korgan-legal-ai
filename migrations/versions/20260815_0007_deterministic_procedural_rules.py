"""add versioned deterministic procedural rule tables

Revision ID: 20260815_0007
Revises: 20260815_0006
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260815_0007"
down_revision = "20260815_0006"
branch_labels = None
depends_on = None


def _common_columns() -> list[sa.Column]:
    return [
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="canonical"),
        sa.Column("reviewed_by", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "procedural_state_duty_rules",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("rule_code", sa.Text(), nullable=False),
        sa.Column("claimant_type", sa.Text(), nullable=False),
        sa.Column("claim_type", sa.Text(), nullable=False),
        sa.Column("rate_percent", sa.Numeric(12, 6), nullable=False),
        sa.Column("cap_mrp", sa.Numeric(18, 4), nullable=True),
        sa.Column("basis_code_id", sa.Text(), nullable=False),
        sa.Column("basis_article", sa.Text(), nullable=False),
        sa.Column("basis_part", sa.Text(), nullable=False, server_default=""),
        sa.Column("basis_point", sa.Text(), nullable=False, server_default=""),
        *_common_columns(),
        sa.CheckConstraint("rate_percent >= 0", name="ck_state_duty_rate_nonnegative"),
        sa.CheckConstraint("cap_mrp IS NULL OR cap_mrp >= 0", name="ck_state_duty_cap_nonnegative"),
        sa.CheckConstraint("status IN ('canonical','pending_review')", name="ck_state_duty_status"),
        sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="ck_state_duty_range"),
        sa.UniqueConstraint("rule_code", "effective_from", name="uq_state_duty_rule_version"),
    )

    op.create_table(
        "procedural_mrp_values",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("value_year", sa.Integer(), nullable=False),
        sa.Column("value_kzt", sa.Numeric(18, 2), nullable=False),
        sa.Column("basis_code_id", sa.Text(), nullable=False),
        sa.Column("basis_article", sa.Text(), nullable=False),
        sa.Column("basis_part", sa.Text(), nullable=False, server_default=""),
        sa.Column("basis_point", sa.Text(), nullable=False, server_default=""),
        *_common_columns(),
        sa.CheckConstraint("value_kzt > 0", name="ck_mrp_positive"),
        sa.CheckConstraint("status IN ('canonical','pending_review')", name="ck_mrp_status"),
        sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="ck_mrp_range"),
        sa.UniqueConstraint("value_year", "effective_from", name="uq_mrp_value_version"),
    )

    op.create_table(
        "procedural_jurisdiction_rules",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("rule_code", sa.Text(), nullable=False),
        sa.Column("dimension", sa.Text(), nullable=False),
        sa.Column("plaintiff_type", sa.Text(), nullable=False),
        sa.Column("defendant_type", sa.Text(), nullable=False),
        sa.Column("dispute_type", sa.Text(), nullable=False),
        sa.Column("result_code", sa.Text(), nullable=False),
        sa.Column("basis_code_id", sa.Text(), nullable=False),
        sa.Column("basis_article", sa.Text(), nullable=False),
        sa.Column("basis_part", sa.Text(), nullable=False, server_default=""),
        sa.Column("basis_point", sa.Text(), nullable=False, server_default=""),
        *_common_columns(),
        sa.CheckConstraint("dimension IN ('subject_matter','territorial')", name="ck_jurisdiction_dimension"),
        sa.CheckConstraint("status IN ('canonical','pending_review')", name="ck_jurisdiction_status"),
        sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="ck_jurisdiction_range"),
        sa.UniqueConstraint("rule_code", "effective_from", name="uq_jurisdiction_rule_version"),
    )

    op.create_table(
        "procedural_deadline_rules",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("rule_code", sa.Text(), nullable=False),
        sa.Column("deadline_type", sa.Text(), nullable=False),
        sa.Column("duration_value", sa.Integer(), nullable=False),
        sa.Column("duration_unit", sa.Text(), nullable=False),
        sa.Column("trigger_event", sa.Text(), nullable=False),
        sa.Column("start_offset_days", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("requires_workday_calendar", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_common_columns(),
        sa.CheckConstraint("duration_value > 0", name="ck_deadline_duration_positive"),
        sa.CheckConstraint("duration_unit IN ('days','months','years')", name="ck_deadline_unit"),
        sa.CheckConstraint("status IN ('canonical','pending_review')", name="ck_deadline_status"),
        sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="ck_deadline_range"),
        sa.UniqueConstraint("rule_code", "effective_from", name="uq_deadline_rule_version"),
    )

    op.create_table(
        "procedural_deadline_bases",
        sa.Column("deadline_rule_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("code_id", sa.Text(), nullable=False),
        sa.Column("article_number", sa.Text(), nullable=False),
        sa.Column("part", sa.Text(), nullable=False, server_default=""),
        sa.Column("point", sa.Text(), nullable=False, server_default=""),
        sa.ForeignKeyConstraint(
            ["deadline_rule_id"],
            ["procedural_deadline_rules.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("deadline_rule_id", "sequence"),
    )

    op.create_index(
        "ix_state_duty_lookup",
        "procedural_state_duty_rules",
        ["status", "claimant_type", "claim_type", "effective_from"],
    )
    op.create_index(
        "ix_jurisdiction_lookup",
        "procedural_jurisdiction_rules",
        ["status", "dimension", "plaintiff_type", "defendant_type", "dispute_type", "effective_from"],
    )
    op.create_index(
        "ix_deadline_lookup",
        "procedural_deadline_rules",
        ["status", "rule_code", "effective_from"],
    )


def downgrade() -> None:
    op.drop_index("ix_deadline_lookup", table_name="procedural_deadline_rules")
    op.drop_index("ix_jurisdiction_lookup", table_name="procedural_jurisdiction_rules")
    op.drop_index("ix_state_duty_lookup", table_name="procedural_state_duty_rules")
    op.drop_table("procedural_deadline_bases")
    op.drop_table("procedural_deadline_rules")
    op.drop_table("procedural_jurisdiction_rules")
    op.drop_table("procedural_mrp_values")
    op.drop_table("procedural_state_duty_rules")
