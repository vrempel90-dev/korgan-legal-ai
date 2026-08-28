from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from korgan import consultation_paid_delivery_guard as guard
from korgan.consultation_quota import ConsultationOrder


class _Message:
    def __init__(self) -> None:
        self.answers: list[str] = []

    async def answer(self, text: str, **kwargs) -> None:
        self.answers.append(text)


@asynccontextmanager
async def _fake_lock(*args, **kwargs):
    yield


def _order(status: str) -> ConsultationOrder:
    return ConsultationOrder(
        id=77,
        user_id=12345,
        chat_id=12345,
        question="Оплаченный вопрос",
        case_context="контекст",
        language="ru",
        amount_kzt=1000,
        status=status,
    )


def test_second_paid_consultation_delivery_does_not_call_ai_again(monkeypatch) -> None:
    message = _Message()

    async def fake_get(order_id: int, user_id: int):
        assert order_id == 77
        assert user_id == 12345
        return _order("consumed")

    async def forbidden_original(*args, **kwargs):
        raise AssertionError("consumed paid consultation must never invoke delivery/AI again")

    monkeypatch.setattr(guard.store, "_require_pool", lambda: object())
    monkeypatch.setattr(guard.store, "get_consultation_order", fake_get)
    monkeypatch.setattr(guard, "payment_operation_lock", _fake_lock)
    monkeypatch.setattr(guard, "_ORIGINAL_DELIVER", forbidden_original)

    asyncio.run(guard._guarded_deliver_paid_order(message, None, _order("paid")))

    assert len(message.answers) == 1
    assert "уже была выдана" in message.answers[0]
    assert "Повторная оплата не нужна" in message.answers[0]


def test_unconfirmed_paid_consultation_never_calls_delivery(monkeypatch) -> None:
    message = _Message()

    async def fake_get(order_id: int, user_id: int):
        return _order("pending")

    async def forbidden_original(*args, **kwargs):
        raise AssertionError("unconfirmed consultation must never invoke paid delivery")

    monkeypatch.setattr(guard.store, "_require_pool", lambda: object())
    monkeypatch.setattr(guard.store, "get_consultation_order", fake_get)
    monkeypatch.setattr(guard, "payment_operation_lock", _fake_lock)
    monkeypatch.setattr(guard, "_ORIGINAL_DELIVER", forbidden_original)

    asyncio.run(guard._guarded_deliver_paid_order(message, None, _order("paid")))

    assert len(message.answers) == 1
    assert "ещё не подтверждена" in message.answers[0]
