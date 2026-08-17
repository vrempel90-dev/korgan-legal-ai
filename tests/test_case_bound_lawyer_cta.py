from __future__ import annotations

import asyncio
from urllib.parse import unquote

from korgan.case_reference import (
    case_reference_from_filename,
    consultation_callback_data,
    document_kind_from_filename,
    ensure_case_reference,
    filename_with_case_reference,
    valid_case_reference,
)
from korgan.contact_handlers import whatsapp_url_for_case
from korgan.localized_transport import lawyer_consultation_markup, lawyer_consultation_text


class FakeState:
    def __init__(self) -> None:
        self.data: dict = {}

    async def get_data(self) -> dict:
        return dict(self.data)

    async def update_data(self, **kwargs) -> None:
        self.data.update(kwargs)


def test_case_reference_is_stable_inside_current_case_state() -> None:
    state = FakeState()
    first = asyncio.run(ensure_case_reference(state))
    second = asyncio.run(ensure_case_reference(state))

    assert first == second
    assert valid_case_reference(first)
    assert state.data["case_reference"] == first


def test_all_supported_document_filenames_can_carry_same_case_reference() -> None:
    reference = "KRG-260817-A1B2C3"
    names = {
        "claim": "KORGAN_iskovoe_zayavlenie.docx",
        "pretrial": "KORGAN_dosudebnaya_pretenziya.docx",
        "response": "KORGAN_otzyv_na_isk.docx",
        "contract": "KORGAN_dogovor.docx",
    }

    for kind, base_name in names.items():
        filename = filename_with_case_reference(base_name, reference)
        assert filename.startswith(f"KORGAN_{reference}_")
        assert case_reference_from_filename(filename) == reference
        assert document_kind_from_filename(filename) == kind


def test_initial_cta_registers_case_before_opening_whatsapp() -> None:
    reference = "KRG-260817-A1B2C3"
    markup = lawyer_consultation_markup("ru", reference, "claim")
    yes = markup.inline_keyboard[0][0]
    no = markup.inline_keyboard[1][0]

    assert yes.url is None
    assert yes.callback_data == consultation_callback_data(reference, "claim")
    assert no.callback_data == "lawyer:decline"
    assert reference in lawyer_consultation_text("ru", reference, "claim")


def test_whatsapp_message_contains_only_safe_case_context() -> None:
    reference = "KRG-260817-A1B2C3"
    url = whatsapp_url_for_case(reference, "claim", "ru")
    decoded = unquote(url)

    assert url.startswith("https://wa.me/77005000553?text=")
    assert reference in decoded
    assert "Исковое заявление" in decoded
    assert "ИИН" not in decoded
    assert "БИН" not in decoded
    assert "telegram" not in decoded.lower()
