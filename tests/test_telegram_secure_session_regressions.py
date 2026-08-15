"""Regression tests for the encrypted Telegram session layer.

These lock the security properties that make Telegram a pure transport: no plaintext subject or
case text at rest, fail-closed handling of unreadable ciphertext, and consent that cannot be
bypassed or silently carried over to a superseded privacy version.
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text

from korgan_legal_ai.telegram.crypto import SessionCrypto, SessionCryptoError
from korgan_legal_ai.telegram.postgres_session import PostgresSessionStore
from korgan_legal_ai.telegram.runtime import TelegramRuntime
from korgan_legal_ai.telegram.session import SessionState, TelegramSession

DB_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL is required")

PRIVACY_V2 = "2026-08-15-v2"
ROOT_KEY = bytes(range(32))
ROTATED_KEY = bytes(range(32, 64))


class FakeAPI:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def send_message(self, chat_id: int, value: str, *, reply_markup=None) -> None:
        self.sent.append(value)

    def answer_callback_query(self, callback_query_id: str) -> None:
        return None


class ForbiddenEngine:
    """Any call means a legal request escaped the consent/fail-closed gates."""

    def process(self, raw_text: str):
        raise AssertionError("LegalEngine must not be reached in this scenario")


def _engine():
    assert DB_URL is not None
    engine = create_engine(DB_URL)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE telegram_sessions"))
    return engine


def _store(engine, *, key: bytes = ROOT_KEY, **kwargs) -> PostgresSessionStore:
    return PostgresSessionStore(engine, SessionCrypto(key), ttl_seconds=3600, **kwargs)


def _message(value: str, *, user_id: int = 555, chat_type: str = "private") -> dict:
    return {
        "update_id": 1,
        "message": {
            "from": {"id": user_id},
            "chat": {"id": user_id, "type": chat_type},
            "text": value,
        },
    }


def _callback(data: str, *, user_id: int = 555) -> dict:
    return {
        "update_id": 2,
        "callback_query": {
            "id": "cb",
            "from": {"id": user_id},
            "message": {"chat": {"id": user_id, "type": "private"}},
            "data": data,
        },
    }


def _table_bytes(engine) -> bytes:
    """Everything stored in the table, rendered as raw bytes for plaintext scanning."""
    with engine.connect() as connection:
        rows = connection.execute(text("SELECT * FROM telegram_sessions")).mappings().all()
    return repr([dict(row) for row in rows]).encode("utf-8", errors="ignore")


def test_no_plaintext_subject_or_case_text_anywhere_in_the_table() -> None:
    engine = _engine()
    store = _store(engine)
    user_id = 918273645
    secret = "ТОО «Альфа» требует взыскать 12 345 678 тенге с ТОО «Бета»"

    store.save(
        user_id,
        TelegramSession(
            language="kk",
            consent_version=PRIVACY_V2,
            state=SessionState.AWAITING_CLARIFICATION,
            case_buffer=secret,
        ),
    )

    dump = _table_bytes(engine)
    assert str(user_id).encode("ascii") not in dump
    assert secret.encode("utf-8") not in dump
    for fragment in ("Альфа", "Бета", "12 345 678"):
        assert fragment.encode("utf-8") not in dump

    # The same data is still recoverable through the crypto layer only.
    assert store.get(user_id).case_buffer == secret


def test_tampered_ciphertext_is_destroyed_and_never_used() -> None:
    engine = _engine()
    store = _store(engine)
    store.save(
        555,
        TelegramSession(
            consent_version=PRIVACY_V2,
            state=SessionState.AWAITING_CLARIFICATION,
            case_buffer="исходный текст дела",
        ),
    )

    with engine.begin() as connection:
        row = connection.execute(text("SELECT encrypted_case FROM telegram_sessions")).one()
        tampered = bytearray(bytes(row[0]))
        tampered[-1] ^= 0x01
        connection.execute(
            text("UPDATE telegram_sessions SET encrypted_case = :value"),
            {"value": bytes(tampered)},
        )

    restored = store.get(555)

    # Fail closed: no partially trusted state survives, and the poisoned row is gone.
    assert restored.case_buffer is None
    assert restored.consent_version is None
    assert restored.state == SessionState.LANGUAGE
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT count(*) FROM telegram_sessions")
        ).scalar_one() == 0


def test_master_key_rotation_fails_closed_without_wedging_the_bot() -> None:
    engine = _engine()
    _store(engine).save(
        555,
        TelegramSession(
            consent_version=PRIVACY_V2,
            state=SessionState.AWAITING_CLARIFICATION,
            case_buffer="текст дела под старым ключом",
        ),
    )

    rotated = _store(engine, key=ROTATED_KEY)
    api = FakeAPI()
    runtime = TelegramRuntime(
        api=api,
        engine=ForbiddenEngine(),
        sessions=rotated,
        privacy_version=PRIVACY_V2,
    )

    # A session written under the previous key must not crash the update handler.
    runtime.handle_update(_message("продолжаю описание дела"))

    assert api.sent, "the user must still receive an answer"
    assert any("условия обработки данных" in value for value in api.sent)

    # Rotating the master key rotates the HMAC branch too, so the old row is no longer addressable
    # under the new pseudonym. The user restarts from consent with no case text carried over.
    restored = rotated.get(555)
    assert restored.case_buffer is None
    assert restored.consent_version is None

    # The row written under the new key holds nothing from before the rotation.
    new_subject = SessionCrypto(ROTATED_KEY).subject_hmac(555)
    with engine.connect() as connection:
        current = connection.execute(
            text(
                "SELECT consent_version, encrypted_case FROM telegram_sessions "
                "WHERE subject_hmac = :subject"
            ),
            {"subject": new_subject},
        ).mappings().one()
    assert current["encrypted_case"] is None
    assert current["consent_version"] is None

    # The pre-rotation row survives as an orphan: a different pseudonym makes it unaddressable and
    # the rotated key cannot read it. It is inert but not self-cleaning, which is why rotation is
    # documented as requiring an explicit purge instead of waiting for TTL expiry.
    with engine.connect() as connection:
        orphans = connection.execute(
            text(
                "SELECT encrypted_case, case_nonce FROM telegram_sessions "
                "WHERE subject_hmac <> :subject"
            ),
            {"subject": new_subject},
        ).mappings().all()
    assert len(orphans) == 1
    with pytest.raises(SessionCryptoError):
        SessionCrypto(ROTATED_KEY).decrypt_case(
            new_subject,
            bytes(orphans[0]["encrypted_case"]),
            bytes(orphans[0]["case_nonce"]),
        )


def test_unreadable_stored_state_does_not_stop_the_polling_loop() -> None:
    engine = _engine()
    store = _store(engine)
    store.save(
        555,
        TelegramSession(consent_version=PRIVACY_V2, state=SessionState.AWAITING_CLAIM),
    )
    # A value no enum member matches, e.g. written by a newer/rolled-back deployment.
    with engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE telegram_sessions DROP CONSTRAINT ck_telegram_session_state")
        )
        connection.execute(text("UPDATE telegram_sessions SET state = 'unknown_state'"))

    try:
        restored = store.get(555)
        assert restored.state == SessionState.LANGUAGE
        assert restored.consent_version is None
    finally:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE telegram_sessions"))
            connection.execute(
                text(
                    "ALTER TABLE telegram_sessions ADD CONSTRAINT ck_telegram_session_state "
                    "CHECK (state IN ('language','privacy','menu','awaiting_claim',"
                    "'awaiting_clarification'))"
                )
            )


def test_new_privacy_version_erases_case_text_and_blocks_processing() -> None:
    engine = _engine()
    store = _store(engine)
    store.save(
        555,
        TelegramSession(
            consent_version=PRIVACY_V2,
            state=SessionState.AWAITING_CLARIFICATION,
            case_buffer="незавершённый текст дела",
        ),
    )

    api = FakeAPI()
    runtime = TelegramRuntime(
        api=api,
        engine=ForbiddenEngine(),
        sessions=store,
        privacy_version="2026-09-01-v3",
    )
    runtime.handle_update(_message("ещё одно уточнение по делу"))

    # Consent to a superseded policy cannot keep holding the case buffer.
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT encrypted_case, case_nonce FROM telegram_sessions")
        ).mappings().one()
    assert row["encrypted_case"] is None
    assert row["case_nonce"] is None
    assert store.get(555).case_buffer is None
    assert any("условия обработки данных" in value for value in api.sent)

    # Accepting only the *old* version again must not unlock processing either.
    assert store.get(555).consent_version != "2026-09-01-v3"


def test_refusing_consent_deletes_the_whole_session_row() -> None:
    engine = _engine()
    store = _store(engine)
    runtime = TelegramRuntime(
        api=FakeAPI(),
        engine=ForbiddenEngine(),
        sessions=store,
        privacy_version=PRIVACY_V2,
    )

    runtime.handle_update(_message("/start"))
    runtime.handle_update(_callback("lang:ru"))
    runtime.handle_update(_callback("consent:accept"))
    runtime.handle_update(_callback("flow:claim"))
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT count(*) FROM telegram_sessions")
        ).scalar_one() == 1

    runtime.handle_update(_callback("consent:decline"))

    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT count(*) FROM telegram_sessions")
        ).scalar_one() == 0


def test_reading_state_never_creates_a_row_for_a_non_consenting_contact() -> None:
    engine = _engine()
    store = _store(engine)
    runtime = TelegramRuntime(
        api=FakeAPI(),
        engine=ForbiddenEngine(),
        sessions=store,
        privacy_version=PRIVACY_V2,
    )

    # A group message is rejected before anything is processed.
    runtime.handle_update(_message("дело в группе", user_id=900001, chat_type="group"))
    # A user who only asks for help never agreed to anything.
    runtime.handle_update(_message("/help", user_id=900002))

    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT count(*) FROM telegram_sessions")
        ).scalar_one() == 0


def test_expiry_removes_the_previous_case_and_capacity_is_bounded() -> None:
    engine = _engine()
    store = _store(engine, max_sessions=3, purge_interval_seconds=0.0)

    for user_id in range(1, 6):
        store.save(
            user_id,
            TelegramSession(
                consent_version=PRIVACY_V2,
                state=SessionState.AWAITING_CLAIM,
                case_buffer=f"дело пользователя {user_id}",
            ),
        )

    store.purge_expired()
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT count(*) FROM telegram_sessions")
        ).scalar_one() == 3

    # An expired row is never returned, even before the timed purge runs.
    store.save(
        99,
        TelegramSession(
            consent_version=PRIVACY_V2,
            state=SessionState.AWAITING_CLARIFICATION,
            case_buffer="протухшее дело",
        ),
    )
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE telegram_sessions SET expires_at = now() - interval '1 second'")
        )

    restored = store.get(99)
    assert restored.case_buffer is None
    assert restored.consent_version is None
    assert restored.state == SessionState.LANGUAGE
