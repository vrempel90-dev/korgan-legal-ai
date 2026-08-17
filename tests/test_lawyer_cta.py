from __future__ import annotations

from aiogram.types import BufferedInputFile

from korgan.localized_transport import (
    is_generated_korgan_document,
    lawyer_consultation_markup,
    lawyer_consultation_text,
    short_document_caption,
)


def test_only_generated_korgan_documents_receive_cta() -> None:
    generated = BufferedInputFile(b"test", filename="KORGAN_dosudebnaya_pretenziya.docx")
    upload = BufferedInputFile(b"test", filename="dogovor_clienta.docx")
    assert is_generated_korgan_document(generated)
    assert not is_generated_korgan_document(upload)


def test_all_current_document_types_have_short_captions() -> None:
    cases = {
        "KORGAN_iskovoe_zayavlenie.docx": "Исковое заявление",
        "KORGAN_dosudebnaya_pretenziya.docx": "Досудебная претензия",
        "KORGAN_otzyv_na_isk.docx": "Отзыв на иск",
        "KORGAN_dogovor.docx": "Договор",
    }
    for filename, expected in cases.items():
        caption = short_document_caption(filename, "ru")
        assert expected in caption
        assert "QUALITY" not in caption
        assert "PRELIMINARY" not in caption
        assert "NEEDS_VERIFICATION" not in caption


def test_lawyer_cta_is_paid_and_uses_requested_whatsapp_number() -> None:
    text = lawyer_consultation_text("ru")
    markup = lawyer_consultation_markup("ru")
    yes = markup.inline_keyboard[0][0]
    no = markup.inline_keyboard[1][0]

    assert "платную консультацию" in text
    assert "+7 700 500 05 53" in text
    assert yes.url is not None
    assert "77005000553" in yes.url
    assert "Да, получить консультацию" in yes.text
    assert no.callback_data == "lawyer:decline"
    assert no.text == "❌ Нет"
