from __future__ import annotations

import asyncio
import inspect

from korgan.auto_payment_runtime import _reserve_release, auto_payment_receipt_received, install_auto_payment
from korgan.document_category_router import preferred_document_category
from korgan.pretrial_response import is_pretrial_response_request
from korgan.pretrial_response_runtime import install_pretrial_response_transport
from korgan.ui import documents_menu


def _callbacks(markup) -> list[str]:
    return [button.callback_data for row in markup.inline_keyboard for button in row if button.callback_data]


def test_pretrial_response_intent_is_separate_from_pretrial_and_claim_response() -> None:
    # Low-level parser keeps the former alias for compatibility with already
    # stored/internal text. Runtime/category routing no longer exposes it.
    assert is_pretrial_response_request("подготовь отзыв на претензию по этим материалам")
    assert is_pretrial_response_request("составь ответ на досудебную претензию")
    assert not is_pretrial_response_request("подготовь досудебную претензию")
    assert not is_pretrial_response_request("подготовь отзыв на иск")
    assert not is_pretrial_response_request("как составить ответ на претензию?")


def test_document_category_prefers_pretrial_response() -> None:
    assert preferred_document_category("подготовь отзыв на претензию") is None
    assert preferred_document_category("составь ответ на досудебную претензию") == "pretrial_response"
    assert preferred_document_category("подготовь досудебную претензию") == "pretrial"
    assert preferred_document_category("подготовь отзыв на иск") == "response"
    assert preferred_document_category("претензия была направлена, подготовь иск") == "claim"


def test_documents_menu_keeps_existing_buttons_and_adds_pretrial_response() -> None:
    callbacks = _callbacks(documents_menu("ru"))
    assert callbacks == [
        "doc:claim",
        "doc:pretrial",
        "doc:pretrial_response",
        "doc:response",
        "doc:contract",
        "menu:main",
    ]


def test_new_document_is_known_to_transport_and_payment() -> None:
    from korgan import localized_transport, payment

    install_pretrial_response_transport()
    assert localized_transport._DOCUMENT_KINDS["korgan_otvet_na_pretenziyu.docx"] == "pretrial_response"
    # Legacy filename remains recognized only so an already-held document from
    # an older deployment can still be released after payment.
    assert localized_transport._DOCUMENT_KINDS["korgan_otzyv_na_pretenziyu.docx"] == "pretrial_response"
    assert payment.document_label("pretrial_response", "ru") == "ответ на претензию"
    assert "Ответ на претензию" in localized_transport._document_client_caption("pretrial_response", "ru")


def test_legacy_payment_offer_requires_ai_and_admin_confirmation() -> None:
    from korgan import payment_gate

    install_auto_payment()
    text = payment_gate.payment_offer_text("claim", "ru", 1000)
    assert "KORGAN AI" in text
    assert "администратор" in text.lower()
    assert "подтверждения оплаты" in text.lower()


def test_legacy_auto_release_is_guarded_and_consumed_before_copy() -> None:
    source = inspect.getsource(auto_payment_receipt_received)
    reservation_source = inspect.getsource(_reserve_release)
    reserve = source.index("await _reserve_release(")
    release = source.index("await message.bot.copy_message(")

    assert reserve < release
    assert "async with _release_lock(transaction_key)" in reservation_source
    assert "admin_confirmed=admin_confirmed" in reservation_source
    assert "[-100:]" in reservation_source
    assert reservation_source.index("can_release_paid_document(") < reservation_source.index("await state.update_data(")


def test_legacy_auto_release_reservation_is_atomic() -> None:
    transaction_key = "123:456:claim"

    class State:
        def __init__(self):
            self.data = {"payment_admin_confirmed_transactions": {transaction_key: True}}

        async def get_data(self):
            await asyncio.sleep(0)
            return dict(self.data)

        async def update_data(self, **kwargs):
            await asyncio.sleep(0)
            self.data.update(kwargs)

    state = State()

    async def reserve_twice():
        return await asyncio.gather(
            _reserve_release(state, transaction_key=transaction_key, receipt_hash="hash", kind="claim"),
            _reserve_release(state, transaction_key=transaction_key, receipt_hash="hash", kind="claim"),
        )

    assert sorted(asyncio.run(reserve_twice())) == ["replay", "reserved"]


def test_accepted_receipt_history_is_bounded() -> None:
    transaction_key = "123:789:claim"

    class State:
        def __init__(self):
            self.data = {
                "payment_admin_confirmed_transactions": {transaction_key: True},
                "payment_accepted_receipts": {f"hash-{index}": f"old-{index}" for index in range(100)},
            }

        async def get_data(self):
            return dict(self.data)

        async def update_data(self, **kwargs):
            self.data.update(kwargs)

    state = State()
    result = asyncio.run(
        _reserve_release(state, transaction_key=transaction_key, receipt_hash="new-hash", kind="claim")
    )

    assert result == "reserved"
    assert len(state.data["payment_accepted_receipts"]) == 100
    assert "hash-0" not in state.data["payment_accepted_receipts"]
    assert state.data["payment_accepted_receipts"]["new-hash"] == transaction_key
