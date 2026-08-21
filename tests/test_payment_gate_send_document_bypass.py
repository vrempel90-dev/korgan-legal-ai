from __future__ import annotations

from pathlib import Path

from aiogram.types import BufferedInputFile

from korgan.localized_transport import _generated_document_kind


def test_claim_filename_is_recognized_as_paid_document() -> None:
    doc = BufferedInputFile(b"test", filename="KORGAN_iskovoe_zayavlenie.docx")
    assert _generated_document_kind(doc) == "claim"


def test_payment_gate_wraps_direct_send_document_path() -> None:
    source = Path("korgan/payment_gate.py").read_text(encoding="utf-8")
    assert "async def payment_aware_send_document" in source
    assert "method = SendDocument(chat_id=chat_id, document=document, **kwargs)" in source
    assert "return await payment_aware_call(self, method, request_timeout=request_timeout)" in source
    assert "LocalizedClientSafeBot.send_document = payment_aware_send_document" in source
