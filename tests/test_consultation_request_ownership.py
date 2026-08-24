from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from korgan import bot as base_bot
import korgan.consultation_quota_runtime as quota_runtime
from korgan.consultation_quota_runtime import _DELIVERED, _STALE, _send_consultation_answer
from korgan.request_scope import (
    consultation_request_is_current,
    start_new_consultation_request,
    start_new_document_request,
)


class FakeState:
    def __init__(self, data: dict | None = None) -> None:
        self.data = dict(data or {})

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
    def __init__(self, text: str | None = None) -> None:
        self.text = text
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


def test_consultation_token_update_is_partial_and_preserves_unrelated_state() -> None:
    class PartialOnlyState(FakeState):
        async def set_data(self, data: dict) -> None:
            raise AssertionError("consultation token update must not replace the full FSM snapshot")

    async def scenario() -> None:
        state = PartialOnlyState({"language": "kk", "facts": ["keep me"], "payment_kind": "contract"})
        request_id = await start_new_consultation_request(state)
        assert state.data["consultation_request_id"] == request_id
        assert state.data["language"] == "kk"
        assert state.data["facts"] == ["keep me"]
        assert state.data["payment_kind"] == "contract"

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


def test_stale_consultation_exception_does_not_emit_old_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        class Service:
            async def consult(self, question: str, *, case_context: str, language: str):
                started.set()
                await release.wait()
                raise RuntimeError("old request failed")

        monkeypatch.setattr(base_bot, "service", Service())
        state = FakeState({"language": "ru"})
        message = FakeMessage()
        task = asyncio.create_task(
            _send_consultation_answer(
                message,
                state,
                question="old",
                case_context="",
                language="ru",
            )
        )
        await started.wait()
        await start_new_document_request(state, kind="pretrial", mode="pretrial_details")
        release.set()

        assert await task == _STALE
        assert message.answers == []

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


def test_paid_branch_question_invalidates_older_consultation_before_payment_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def language(_state):
        return "ru"

    async def context(_state):
        return "case context"

    async def no_free_slot(user_id: int, limit: int):
        return None

    async def create_order(**kwargs):
        return SimpleNamespace(id=77)

    monkeypatch.setattr(quota_runtime, "get_settings", lambda: SimpleNamespace(free_consultations_per_day=1, consultation_price_kzt=1000))
    monkeypatch.setattr(base_bot, "_language", language)
    monkeypatch.setattr(base_bot, "_case_context", context)
    monkeypatch.setattr(quota_runtime, "reserve_free_consultation", no_free_slot)
    monkeypatch.setattr(quota_runtime, "create_consultation_order", create_order)
    monkeypatch.setattr(quota_runtime, "consultation_payment_text", lambda *args: "PAYMENT REQUIRED")
    monkeypatch.setattr(quota_runtime, "consultation_payment_markup", lambda *args: None)

    async def scenario() -> None:
        state = FakeState({"consultation_request_id": "old-token", "language": "ru"})
        message = FakeMessage("new paid question")
        await quota_runtime.limited_consultation(message, state)
        assert state.data["consultation_request_id"] != "old-token"
        assert message.answers == ["PAYMENT REQUIRED"]

    asyncio.run(scenario())


def test_stale_paid_attempt_does_not_offer_retry_after_newer_attempt_consumed_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def stale_send(*args, **kwargs):
        return _STALE

    async def consumed_order(order_id: int, user_id: int):
        return SimpleNamespace(status="consumed")

    monkeypatch.setattr(quota_runtime, "_send_consultation_answer", stale_send)
    monkeypatch.setattr(quota_runtime, "get_consultation_order", consumed_order)

    async def scenario() -> None:
        state = FakeState({"facts": []})
        message = FakeMessage()
        order = SimpleNamespace(
            status="paid",
            question="paid question",
            case_context="",
            language="ru",
            id=42,
            user_id=3,
        )
        await quota_runtime._deliver_paid_order(message, state, order)
        assert message.answers == []

    asyncio.run(scenario())
