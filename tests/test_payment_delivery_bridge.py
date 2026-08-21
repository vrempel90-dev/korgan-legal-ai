from __future__ import annotations

import asyncio
from types import SimpleNamespace

from aiogram.types import BufferedInputFile, Message

from korgan import payment_delivery_bridge


class _FakeBot:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def send_document(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        return "sent-after-confirmed-prepayment"


def test_generated_claim_answer_document_routes_through_bot_send_document() -> None:
    original = Message.answer_document
    old_installed = payment_delivery_bridge._INSTALLED
    old_original = payment_delivery_bridge._ORIGINAL_ANSWER_DOCUMENT
    try:
        payment_delivery_bridge._INSTALLED = False
        payment_delivery_bridge._ORIGINAL_ANSWER_DOCUMENT = None
        payment_delivery_bridge.install_payment_delivery_bridge()

        bot = _FakeBot()
        fake_message = SimpleNamespace(bot=bot, chat=SimpleNamespace(id=777))
        document = BufferedInputFile(b"docx", filename="KORGAN_iskovoe_zayavlenie.docx")

        result = asyncio.run(
            Message.answer_document(
                fake_message,
                document,
                caption="ready",
                reply_markup=None,
            )
        )

        assert result == "sent-after-confirmed-prepayment"
        assert len(bot.calls) == 1
        call = bot.calls[0]
        assert call["kwargs"]["chat_id"] == 777
        assert call["kwargs"]["document"] is document
        assert call["kwargs"]["caption"] == "ready"
    finally:
        Message.answer_document = original
        payment_delivery_bridge._INSTALLED = old_installed
        payment_delivery_bridge._ORIGINAL_ANSWER_DOCUMENT = old_original


def test_runtime_keeps_delivery_bridge_but_uses_prepayment_before_generation() -> None:
    source = __import__("pathlib").Path("korgan/strict_bot.py").read_text(encoding="utf-8")
    assert "install_payment_gate()" not in source
    assert "install_payment_delivery_bridge()" in source
    assert "install_generation_prepayment_gate()" in source
    assert source.index("install_payment_delivery_bridge()") < source.index("install_generation_prepayment_gate()")
