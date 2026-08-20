from __future__ import annotations

import asyncio
from pathlib import Path

from korgan.payment_gate import _select_storage_admin
from korgan.upload_followup_guard import _NEW_FOLLOWUP, _OLD_FOLLOWUP, _UploadMessageProxy


class _AnswerSink:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def answer(self, text, *args, **kwargs):
        self.messages.append(str(text))
        return "sent"


def test_payment_storage_never_uses_the_paying_client_chat() -> None:
    assert _select_storage_admin({62171871}, 62171871) is None
    assert _select_storage_admin({62171871, 777}, 62171871) == 777
    assert _select_storage_admin({777}, 62171871) == 777


def test_payment_gate_fails_closed_when_no_separate_storage_admin_exists() -> None:
    source = Path("korgan/payment_gate.py").read_text(encoding="utf-8")
    assert "storage_admin_id = _select_storage_admin(admins, user_id)" in source
    assert "storage_admin_id is None" in source
    assert '"chat_id": storage_admin_id' in source
    assert '"Оплата не требуется.' in source
    assert '"chat_id": user_id' not in source


def test_upload_followup_no_longer_pushes_claim_for_other_document_types() -> None:
    sink = _AnswerSink()
    proxy = _UploadMessageProxy(sink)
    text = "✅ Материал разобран.\n\n" + _OLD_FOLLOWUP

    result = asyncio.run(proxy.answer(text))

    assert result == "sent"
    assert len(sink.messages) == 1
    assert _OLD_FOLLOWUP not in sink.messages[0]
    assert _NEW_FOLLOWUP in sink.messages[0]
    assert "попросить подготовить иск" not in sink.messages[0]


def test_runtime_installs_upload_followup_guard_without_replacing_document_routes() -> None:
    source = Path("korgan/strict_bot.py").read_text(encoding="utf-8")
    assert "install_upload_followup_guard()" in source
    assert "install_payment_gate()" in source
    assert "install_payment_delivery_bridge()" in source
