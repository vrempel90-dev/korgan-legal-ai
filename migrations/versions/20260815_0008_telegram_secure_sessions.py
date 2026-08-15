"""add encrypted Telegram session storage

Revision ID: 20260815_0008
Revises: 20260815_0007
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260815_0008"
down_revision = "20260815_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_sessions",
        sa.Column("subject_hmac", sa.LargeBinary(length=32), primary_key=True, nullable=False),
        sa.Column("language", sa.Text(), nullable=False, server_default="ru"),
        sa.Column("consent_version", sa.Text(), nullable=True),
        sa.Column("state", sa.Text(), nullable=False, server_default="language"),
        sa.Column("encrypted_case", sa.LargeBinary(), nullable=True),
        sa.Column("case_nonce", sa.LargeBinary(length=12), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("octet_length(subject_hmac) = 32", name="ck_telegram_session_subject_hmac_length"),
        sa.CheckConstraint("language IN ('ru','kk')", name="ck_telegram_session_language"),
        sa.CheckConstraint(
            "state IN ('language','privacy','menu','awaiting_claim','awaiting_clarification')",
            name="ck_telegram_session_state",
        ),
        sa.CheckConstraint(
            "(encrypted_case IS NULL AND case_nonce IS NULL) OR "
            "(encrypted_case IS NOT NULL AND case_nonce IS NOT NULL AND octet_length(case_nonce) = 12)",
            name="ck_telegram_session_cipher_pair",
        ),
    )
    op.create_index("ix_telegram_sessions_expires_at", "telegram_sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_telegram_sessions_expires_at", table_name="telegram_sessions")
    op.drop_table("telegram_sessions")
