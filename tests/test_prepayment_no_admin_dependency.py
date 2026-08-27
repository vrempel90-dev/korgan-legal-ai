from __future__ import annotations

import asyncio
from types import SimpleNamespace

from korgan import prepayment_gate
from korgan.config import Settings


def _settings() -> Settings:
    return Settings(
        telegram_bot_token="123456:TEST_TOKEN",
        openai_api_key="test-openai",
        payments_enabled=True,
        kaspi_payment_url="https://pay.kaspi.kz/pay/test",
        kaspi_payment_recipient="OpenCourt (KORGAN)",
        document_price_kzt=1000,
        admin_telegram_ids="62171871",
    )


def test_local_transaction_id_is_negative_stable_and_request_scoped() -> None:
    settings = _settings()
    first = prepayment_gate._prepayment_transaction_id(settings, 62171871, "request-1", "claim")
    assert first < 0
    assert first == prepayment_gate._prepayment_transaction_id(settings, 62171871, "request-1", "claim")
    assert first != prepayment_gate._prepayment_transaction_id(settings, 62171871, "request-2", "claim")
    assert first != prepayment_gate._prepayment_transaction_id(settings, 62171871, "request-1", "contract")
    assert first != prepayment_gate._prepayment_transaction_id(settings, 62171872, "request-1", "claim")


def test_payment_offer_does_not_depend_on_separate_admin_chat(monkeypatch) -> None:
    settings = _settings()

    class State:
        def __init__(self) -> None:
            self.data = {
                "request_id": "request-1",
                "request_kind": "claim",
                "language": "ru",
            }

        async def get_data(self):
            return dict(self.data)

        async def update_data(self, **kwargs):
            self.data.update(kwargs)

    class Bot:
        async def send_message(self, *_args, **_kwargs):
            raise AssertionError("automatic prepayment must not send a reservation to an admin chat")

    class Message:
        chat = SimpleNamespace(id=62171871)
        bot = Bot()

        def __init__(self) -> None:
            self.answers: list[tuple[str, dict[str, object]]] = []

        async def answer(self, text: str, **kwargs):
            self.answers.append((text, kwargs))

    monkeypatch.setattr(prepayment_gate, "get_settings", lambda: settings)
    state = State()
    message = Message()
    allowed = asyncio.run(prepayment_gate.ensure_prepayment(message, state, kind="claim"))

    assert allowed is False
    assert state.data["mode"] == "prepayment_waiting"
    assert int(state.data["prepayment_transaction_id"]) < 0
    assert state.data["prepayment_request_id"] == "request-1"
    assert state.data["prepayment_kind"] == "claim"
    assert message.answers
    assert "Оплата перед подготовкой документа" in message.answers[-1][0]
    assert "временно недоступна" not in " ".join(text for text, _ in message.answers)
    assert "reply_markup" in message.answers[-1][1]
