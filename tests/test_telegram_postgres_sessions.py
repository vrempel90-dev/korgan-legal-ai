from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text

from korgan_legal_ai.telegram.crypto import SessionCrypto
from korgan_legal_ai.telegram.postgres_session import PostgresSessionStore
from korgan_legal_ai.telegram.session import SessionState, TelegramSession

DB_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL is required")


def _store() -> tuple[PostgresSessionStore, object]:
    assert DB_URL is not None
    engine = create_engine(DB_URL)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE telegram_sessions"))
    return PostgresSessionStore(engine, SessionCrypto(bytes(range(32))), ttl_seconds=3600), engine


def test_postgres_session_roundtrip_never_stores_plain_user_or_case_text() -> None:
    store, engine = _store()
    user_id = 987654321
    secret = "Очень секретный текст юридического дела"
    session = TelegramSession(
        language="kk",
        consent_version="2026-08-15-v2",
        state=SessionState.AWAITING_CLARIFICATION,
        case_buffer=secret,
    )

    store.save(user_id, session)

    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT subject_hmac, language, consent_version, state,
                       encrypted_case, case_nonce
                FROM telegram_sessions
                """
            )
        ).mappings().one()

    assert len(bytes(row["subject_hmac"])) == 32
    assert str(user_id).encode("ascii") not in bytes(row["subject_hmac"])
    assert secret.encode("utf-8") not in bytes(row["encrypted_case"])
    assert len(bytes(row["case_nonce"])) == 12

    loaded = store.get(user_id)
    assert loaded.language == "kk"
    assert loaded.consent_version == "2026-08-15-v2"
    assert loaded.state == SessionState.AWAITING_CLARIFICATION
    assert loaded.case_buffer == secret


def test_clear_case_and_delete_remove_sensitive_session_data() -> None:
    store, engine = _store()
    user_id = 42
    store.save(
        user_id,
        TelegramSession(
            consent_version="2026-08-15-v2",
            state=SessionState.AWAITING_CLAIM,
            case_buffer="case text",
        ),
    )

    cleared = store.clear_case(user_id)
    assert cleared.case_buffer is None
    assert cleared.state == SessionState.MENU

    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT encrypted_case, case_nonce FROM telegram_sessions")
        ).mappings().one()
    assert row["encrypted_case"] is None
    assert row["case_nonce"] is None

    store.delete(user_id)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM telegram_sessions")).scalar_one() == 0


def test_expired_session_is_purged_before_read() -> None:
    store, engine = _store()
    user_id = 77
    store.save(
        user_id,
        TelegramSession(
            language="kk",
            consent_version="old",
            state=SessionState.AWAITING_CLAIM,
            case_buffer="expired case",
        ),
    )
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE telegram_sessions SET expires_at = :past"),
            {"past": datetime.now(timezone.utc) - timedelta(seconds=1)},
        )

    loaded = store.get(user_id)
    assert loaded.language == "ru"
    assert loaded.consent_version is None
    assert loaded.state == SessionState.LANGUAGE
    assert loaded.case_buffer is None
