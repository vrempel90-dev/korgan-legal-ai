from __future__ import annotations

from aiogram.types import BufferedInputFile

from korgan.localized_transport import (
    is_generated_korgan_document,
    lawyer_consultation_markup,
    lawyer_consultation_text,
    short_document_caption,
)


CASE_REFERENCE = "KRG-260817-A1B2C3"


def test_only_generated_korgan_documents_receive_cta() -> None:
    generated = BufferedInputFile(b"test", filename=f"KORGAN_{CASE_REFERENCE}_dosudebnaya_pretenziya.docx")
    upload = BufferedInputFile(b"test", filename="dogovor_clienta.docx")
    assert is_generated_korgan_document(generated)
    assert not is_generated_korgan_document(upload)


def test_all_current_document_types_have_short_captions() -> None:
    cases = {
        f"KORGAN_{CASE_REFERENCE}_iskovoe_zayavlenie.docx": "Исковое заявление",
        f"KORGAN_{CASE_REFERENCE}_dosudebnaya_pretenziya.docx": "Досудебная претензия",
        f"KORGAN_{CASE_REFERENCE}_otzyv_na_isk.docx": "Отзыв на иск",
        f"KORGAN_{CASE_REFERENCE}_dogovor.docx": "Договор",
    }
    for filename, expected in cases.items():
        caption = short_document_caption(filename, "ru")
        assert expected in caption
        assert "QUALITY" not in caption
        assert "PRELIMINARY" not in caption
        assert "NEEDS_VERIFICATION" not in caption


def test_lawyer_cta_registers_concrete_case_before_whatsapp() -> None:
    text = lawyer_consultation_text("ru", CASE_REFERENCE, "claim")
    markup = lawyer_consultation_markup("ru", CASE_REFERENCE, "claim")
    yes = markup.inline_keyboard[0][0]
    no = markup.inline_keyboard[1][0]

    assert "платную консультацию" in text
    assert "+7 700 500 05 53" in text
    assert CASE_REFERENCE in text
    assert "Исковое заявление" in text

    # The first click must register the request in Telegram state. WhatsApp opens
    # only on the confirmation step, so the consultation request is not lost.
    assert yes.url is None
    assert yes.callback_data == f"lawyer:request:{CASE_REFERENCE}:claim"
    assert "по этому делу" in yes.text
    assert no.callback_data == "lawyer:decline"
    assert no.text == "❌ Нет"
