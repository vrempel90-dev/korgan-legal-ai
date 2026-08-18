from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from aiogram.methods import SendDocument
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup

from korgan.localized_transport import _prepare_send_document


def test_real_pretrial_send_document_gets_compact_paid_review_cta() -> None:
    method = SendDocument(
        chat_id=123,
        document=BufferedInputFile(b"docx", filename="KORGAN_dosudebnaya_pretenziya.docx"),
        caption="✅ Досудебная претензия сформирована в Word (.docx).",
    )

    prepared = _prepare_send_document(method, "ru")

    assert "Рекомендуем проверить досудебную претензию у профессионального юриста" in (prepared.caption or "")
    assert "Проверка платная. Доп. услуги — отдельно." in (prepared.caption or "")
    assert "http" not in (prepared.caption or "")
    assert isinstance(prepared.reply_markup, InlineKeyboardMarkup)

    yes_button, no_button = prepared.reply_markup.inline_keyboard[0]
    assert yes_button.text == "✅ Да"
    assert yes_button.url is not None
    assert yes_button.url.startswith("https://wa.me/77005000553?text=")
    assert "KORGAN: платная проверка претензии." == parse_qs(urlparse(yes_button.url).query)["text"][0]
    assert no_button.text == "❌ Нет"
    assert no_button.url is None
    assert no_button.callback_data == "lawyer_review:pretrial:no"


def test_real_send_document_cta_covers_all_four_categories() -> None:
    expected = {
        "KORGAN_iskovoe_zayavlenie.docx": "lawyer_review:claim:no",
        "KORGAN_dosudebnaya_pretenziya.docx": "lawyer_review:pretrial:no",
        "KORGAN_otzyv_na_isk.docx": "lawyer_review:response:no",
        "KORGAN_dogovor.docx": "lawyer_review:contract:no",
    }
    for filename, callback in expected.items():
        prepared = _prepare_send_document(
            SendDocument(chat_id=123, document=BufferedInputFile(b"docx", filename=filename)),
            "ru",
        )
        assert isinstance(prepared.reply_markup, InlineKeyboardMarkup)
        yes_button, no_button = prepared.reply_markup.inline_keyboard[0]
        assert yes_button.url is not None
        assert yes_button.url.startswith("https://wa.me/77005000553?text=")
        assert no_button.callback_data == callback
