from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from korgan import auto_payment_runtime


class State:
    def __init__(self, data: dict):
        self.data = dict(data)

    async def get_data(self):
        return dict(self.data)

    async def update_data(self, **kwargs):
        self.data.update(kwargs)


def _payment_state(*, transaction_id: int, confirmed: bool) -> State:
    return State({
        "mode": "payment_receipt",
        "payment_admin_doc_message_id": transaction_id,
        "payment_kind": "claim",
        "payment_language": "ru",
        "payment_signature": "valid",
        "payment_confirmed_transaction_id": transaction_id if confirmed else None,
    })


def _configure_valid_receipt(monkeypatch, *, transaction_id: str = "kaspi-operation-1") -> None:
    settings = SimpleNamespace(admin_ids={99}, document_price_kzt=1000)
    analyzer = SimpleNamespace(analyze=AsyncMock(return_value=SimpleNamespace(
        amount_kzt=1000,
        receipt_or_transaction_id=transaction_id,
        suspicious_signals=[],
    )))
    monkeypatch.setattr(auto_payment_runtime, "get_settings", lambda: settings)
    monkeypatch.setattr(auto_payment_runtime, "verify_user_payment", lambda *args: True)
    monkeypatch.setattr(
        auto_payment_runtime,
        "_receipt_bytes",
        AsyncMock(return_value=(b"receipt bytes", "receipt.jpg", "image/jpeg")),
    )
    monkeypatch.setattr(auto_payment_runtime, "ReceiptAnalyzer", lambda settings: analyzer)
    monkeypatch.setattr(auto_payment_runtime, "receipt_hard_issues", lambda check, amount: [])


def _message():
    return SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        bot=SimpleNamespace(copy_message=AsyncMock()),
        answer=AsyncMock(),
    )


def test_auto_payment_requires_transaction_bound_admin_confirmation(monkeypatch) -> None:
    _configure_valid_receipt(monkeypatch)
    state = _payment_state(transaction_id=42, confirmed=False)
    message = _message()

    asyncio.run(auto_payment_runtime.auto_payment_receipt_received(message, state))

    message.bot.copy_message.assert_not_awaited()
    assert "auto_payment_receipt_fingerprints" not in state.data
    assert "auto_payment_released_transactions" not in state.data


def test_auto_payment_reserves_receipt_and_transaction_before_single_delivery(monkeypatch) -> None:
    _configure_valid_receipt(monkeypatch)
    state = _payment_state(transaction_id=42, confirmed=True)
    message = _message()

    async def submit_twice():
        await auto_payment_runtime.auto_payment_receipt_received(message, state)
        await auto_payment_runtime.auto_payment_receipt_received(message, state)

    asyncio.run(submit_twice())

    message.bot.copy_message.assert_awaited_once()
    assert len(state.data["auto_payment_receipt_fingerprints"]) == 1
    assert state.data["auto_payment_bank_transaction_ids"] == ["kaspioperation1"]
    assert state.data["auto_payment_released_transactions"] == ["123:42:claim"]


def test_auto_payment_rejects_same_receipt_for_another_transaction(monkeypatch) -> None:
    _configure_valid_receipt(monkeypatch)
    first_state = _payment_state(transaction_id=42, confirmed=True)
    first_message = _message()

    async def submit_reused_receipt():
        await auto_payment_runtime.auto_payment_receipt_received(first_message, first_state)
        second_state = _payment_state(transaction_id=43, confirmed=True)
        second_state.data["auto_payment_receipt_fingerprints"] = list(
            first_state.data["auto_payment_receipt_fingerprints"]
        )
        second_message = _message()
        await auto_payment_runtime.auto_payment_receipt_received(second_message, second_state)
        return second_message

    second_message = asyncio.run(submit_reused_receipt())

    first_message.bot.copy_message.assert_awaited_once()
    second_message.bot.copy_message.assert_not_awaited()


def test_auto_payment_without_bank_transaction_id_stays_pending(monkeypatch) -> None:
    _configure_valid_receipt(monkeypatch, transaction_id="")
    state = _payment_state(transaction_id=42, confirmed=True)
    message = _message()

    asyncio.run(auto_payment_runtime.auto_payment_receipt_received(message, state))

    message.bot.copy_message.assert_not_awaited()
    assert "auto_payment_receipt_fingerprints" not in state.data
