from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text

from korgan_legal_ai.domain.exceptions import ClarificationRequired
from korgan_legal_ai.telegram.crypto import SessionCrypto
from korgan_legal_ai.telegram.postgres_session import PostgresSessionStore
from korgan_legal_ai.telegram.runtime import TelegramRuntime
from korgan_legal_ai.telegram.session import SessionState

DB_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL is required")


class FakeAPI:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def send_message(self, chat_id: int, value: str, *, reply_markup=None) -> None:
        self.sent.append(value)

    def answer_callback_query(self, callback_query_id: str) -> None:
        return None


class ClarifyingEngine:
    def process(self, raw_text: str):
        raise ClarificationRequired(["Укажите точную дату исполнения обязательства"])


def _message(value: str) -> dict:
    return {
        "message": {
            "from": {"id": 555},
            "chat": {"id": 555, "type": "private"},
            "text": value,
        }
    }


def _callback(data: str) -> dict:
    return {
        "callback_query": {
            "id": "cb",
            "from": {"id": 555},
            "message": {"chat": {"id": 555, "type": "private"}},
            "data": data,
        }
    }


def test_unfinished_clarification_survives_restart_then_cancel_erases_case() -> None:
    assert DB_URL is not None
    engine = create_engine(DB_URL)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE telegram_sessions"))

    crypto = SessionCrypto(bytes(range(32)))
    first_store = PostgresSessionStore(engine, crypto, ttl_seconds=3600)
    first_runtime = TelegramRuntime(
        api=FakeAPI(),
        engine=ClarifyingEngine(),
        sessions=first_store,
        privacy_version="2026-08-15-v2",
    )

    first_runtime.handle_update(_message("/start"))
    first_runtime.handle_update(_callback("lang:ru"))
    first_runtime.handle_update(_callback("consent:accept"))
    first_runtime.handle_update(_callback("flow:claim"))
    first_runtime.handle_update(_message("ТОО А требует взыскать 1 000 000 тенге с ТОО Б."))

    restarted_store = PostgresSessionStore(engine, crypto, ttl_seconds=3600)
    restored = restarted_store.get(555)
    assert restored.state == SessionState.AWAITING_CLARIFICATION
    assert restored.case_buffer == "ТОО А требует взыскать 1 000 000 тенге с ТОО Б."

    restarted_runtime = TelegramRuntime(
        api=FakeAPI(),
        engine=ClarifyingEngine(),
        sessions=restarted_store,
        privacy_version="2026-08-15-v2",
    )
    restarted_runtime.handle_update(_message("/cancel"))

    after_cancel = restarted_store.get(555)
    assert after_cancel.case_buffer is None
    assert after_cancel.state == SessionState.MENU
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT encrypted_case, case_nonce FROM telegram_sessions")
        ).mappings().one()
    assert row["encrypted_case"] is None
    assert row["case_nonce"] is None
