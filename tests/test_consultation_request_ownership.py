from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from korgan import bot as base_bot
from korgan.consultation_quota_runtime import _DELIVERED, _STALE, _send_consultation_answer
from korgan.request_scope import (
    consultation_request_is_current,
    start_new_consultation_request,
    start_new_document_request,
)


class FakeState:
    def __init__(self, data: dict | None = None) -> None:
        self.data = dict(data or {})
        self.key = SimpleNamespace(bot_id=1, chat_id=2, user_id=3, thread_id=None)

    async def get_data(self) -> dict:
        return dict(self.data)

    async def set_data(self, data: dict) -> None:
        self.data = dict(data)

    async def update_data(self, **kwargs) -> dict:
        self.data.update(kwargs)
        return dict(self.data)


class FakeBot:
    async def send_chat_action(self, chat_id: int, action: str) -> None:
        return None


class FakeMessage:
    def __init__(self) -> None:
        self.chat = SimpleNamespace(id=2)
        self.from_user = SimpleNamespace(id=3)
        self.bot = FakeBot()
        self.answers: list[str] = []

    async def answer(self, text: str, **kwargs) -> None:
        self.answers.append(text)


def test_new_document_request_invalidates_inflight_consultation_token() -> None:
    async def scenario() -> None:
        state = FakeState({"language": "ru", "facts": ["case"]})
        consultation_id = await start_new_consultation_request(state)
        assert await consultation_request_is_current(state, consultation_id)

        await start_new_document_request(state, kind="contract", mode="document_contract")

        assert not await consultation_request_is_current(state, consultation_id)
        assert state.data["request_kind"] == "contract"
        assert "consultation_request_id" not in state.data

    asyncio.run(scenario())


def test_slow_consultation_is_suppressed_after_document_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        class Service:
            async def consult(self, question: str, *, case_context: str, language: str):
                started.set()
                await release.wait()
                return "Старый ответ", ["https://adilet.zan.kz/rus/docs/K940001000_"]

        monkeypatch.setattr(base_bot, "service", Service())
        state = FakeState({"language": "ru", "facts": ["old case"], "consulted_articles": []})
        message = FakeMessage()

        task = asyncio.create_task(
            _send_consultation_answer(
                message,
                state,
                question="старый вопрос",
                case_context="old case",
                language="ru",
            )
        )
        await started.wait()
        await start_new_document_request(state, kind="claim", mode="claim_details")
        release.set()

        result = await task

        assert result == _STALE
        assert message.answers == []
        assert state.data.get("consulted_articles", []) == []
        assert state.data["request_kind"] == "claim"

    asyncio.run(scenario())


def test_newer_consultation_owns_delivery_and_old_answer_is_suppressed(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        old_started = asyncio.Event()
        release_old = asyncio.Event()

        class Service:
            async def consult(self, question: str, *, case_context: str, language: str):
                if question == "old":
                    old_started.set()
                    await release_old.wait()
                    return "OLD ANSWER", []
                return "NEW ANSWER", []

        monkeypatch.setattr(base_bot, "service", Service())
        state = FakeState({"language": "ru", "facts": [], "consulted_articles": []})
        old_message = FakeMessage()
        new_message = FakeMessage()

        old_task = asyncio.create_task(
            _send_consultation_answer(
                old_message,
                state,
                question="old",
                case_context="",
                language="ru",
            )
        )
        await old_started.wait()

        new_result = await _send_consultation_answer(
            new_message,
            state,
            question="new",
            case_context="",
            language="ru",
        )
        release_old.set()
        old_result = await old_task

        assert new_result == _DELIVERED
        assert old_result == _STALE
        assert new_message.answers == ["NEW ANSWER"]
        assert old_message.answers == []

    asyncio.run(scenario())
