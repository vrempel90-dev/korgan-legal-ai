"""allow Telegram document-evidence dialogue states

Revision ID: 20260815_0009
Revises: 20260815_0008
"""
from __future__ import annotations

from alembic import op

revision = "20260815_0009"
down_revision = "20260815_0008"
branch_labels = None
depends_on = None

_OLD_STATES = (
    "language",
    "privacy",
    "menu",
    "awaiting_claim",
    "awaiting_clarification",
)
_NEW_STATES = _OLD_STATES + (
    "awaiting_documents",
    "awaiting_document_clarification",
)


def _constraint(states: tuple[str, ...]) -> str:
    quoted = ",".join(f"'{state}'" for state in states)
    return f"state IN ({quoted})"


def upgrade() -> None:
    op.drop_constraint("ck_telegram_session_state", "telegram_sessions", type_="check")
    op.create_check_constraint(
        "ck_telegram_session_state",
        "telegram_sessions",
        _constraint(_NEW_STATES),
    )


def downgrade() -> None:
    # A rollback must not become impossible merely because a user was in the new document flow.
    op.execute(
        "UPDATE telegram_sessions SET state = 'menu' "
        "WHERE state IN ('awaiting_documents','awaiting_document_clarification')"
    )
    op.drop_constraint("ck_telegram_session_state", "telegram_sessions", type_="check")
    op.create_check_constraint(
        "ck_telegram_session_state",
        "telegram_sessions",
        _constraint(_OLD_STATES),
    )
