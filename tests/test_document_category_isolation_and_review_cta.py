from __future__ import annotations

import asyncio
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from aiogram.types import BufferedInputFile

from korgan.document_category_router import PreferredDocumentCategory, preferred_document_category
from korgan.localized_transport import (
    _claim_client_caption,
    _document_review_markup,
    _document_review_text,
    _generated_document_kind,
)


def test_claim_wins_over_factual_pretrial_mention() -> None:
    text = (
        "Между сторонами заключён договор. Досудебная претензия направлена 10 августа и получена ответчиком. "
        "Основной долг 600 000 тенге. Подготовь исковое заявление о взыскании 600 000 тенге."
    )
    assert preferred_document_category(text) == "claim"


def test_pretrial_wins_over_factual_contract_mention() -> None:
    text = (
        "По договору оказания услуг образовалась задолженность 600 000 тенге. "
        "Подготовь досудебную претензию об оплате задолженности."
    )
    assert preferred_document_category(text) == "pretrial"


def test_contract_owns_contract_request_even_when_claim_is_mentioned() -> None:
    text = (
        "Стороны хотят урегулировать спор до иска. Составь договор возмездного оказания юридических услуг."
    )
    assert preferred_document_category(text) == "contract"


def test_response_owns_response_request_not_claim() -> None:
    assert preferred_document_category("Подготовь отзыв на исковое заявление истца.") == "response"


def test_kazakh_categories_are_isolated() -> None:
    assert preferred_document_category("Сотқа дейінгі талап жіберілді. Талап қою арызын дайында.") == "claim"
    assert preferred_document_category("Шарт бойынша берешек бар. Сотқа дейінгі талапты дайында.") == "pretrial"
    assert preferred_document_category("Талап қою туралы дау бар. Шартты дайында.") == "contract"
    assert preferred_document_category("Талап қою арызына пікірді дайында.") == "response"


def test_claim_waiting_mode_cannot_be_stolen_by_pretrial_words() -> None:
    class State:
        async def get_data(self):
            return {"mode": "universal_claim_waiting"}

    message = SimpleNamespace(text="Досудебная претензия была направлена. Долг 600 000 тенге.")
    result = asyncio.run(PreferredDocumentCategory()(message, State()))
    assert result == {"document_category": "claim"}


def test_other_active_document_modes_are_not_intercepted() -> None:
    class State:
        async def get_data(self):
            return {"mode": "contract_details"}

    message = SimpleNamespace(text="Подготовь исковое заявление")
    assert asyncio.run(PreferredDocumentCategory()(message, State())) is False


def test_generated_document_kind_is_exact_for_all_four_categories() -> None:
    expected = {
        "KORGAN_iskovoe_zayavlenie.docx": "claim",
        "KORGAN_dosudebnaya_pretenziya.docx": "pretrial",
        "KORGAN_sotqa_deyingi_talap.docx": "pretrial",
        "KORGAN_otzyv_na_isk.docx": "response",
        "KORGAN_dogovor.docx": "contract",
    }
    for filename, kind in expected.items():
        document = BufferedInputFile(b"test", filename=filename)
        assert _generated_document_kind(document) == kind

    assert _generated_document_kind(BufferedInputFile(b"test", filename="random.docx")) is None


def test_claim_review_cta_is_compact_paid_yes_no_and_points_to_exact_whatsapp() -> None:
    text = _document_review_text("claim", "ru")
    assert "настoятельно" not in text
    assert "настoятель" not in text
    assert "настo" not in text
    assert "наст" in text
    assert "Проверка этого иска — платная услуга" in text
    assert "Дополнительные юридические услуги оплачиваются отдельно" in text
    assert "Передать иск юристу?" in text
    assert "KORGAN QUALITY" not in text
    assert "PRELIMINARY" not in text

    markup = _document_review_markup("claim", "ru")
    assert len(markup.inline_keyboard) == 1
    assert len(markup.inline_keyboard[0]) == 2
    yes_button, no_button = markup.inline_keyboard[0]
    assert yes_button.text == "✅ Да"
    assert yes_button.url is not None
    assert yes_button.url.startswith("https://wa.me/77005000553?text=")
    query = parse_qs(urlparse(yes_button.url).query)
    prefill = query["text"][0]
    assert "платную проверку именно этого искового заявления" in prefill
    assert "дополнительные юридические услуги оплачиваются отдельно" in prefill
    assert no_button.text == "❌ Нет"
    assert no_button.callback_data == "lawyer_review:claim:no"


def test_claim_file_caption_hides_internal_quality_diagnostics() -> None:
    assert _claim_client_caption("ru") == "✅ Иск сформирован в Word (.docx)."
    assert _claim_client_caption("kk") == "✅ Талап қою арызы Word (.docx) форматында дайын."
    assert "QUALITY" not in _claim_client_caption("ru")
    assert "PRELIMINARY" not in _claim_client_caption("ru")


def test_other_review_ctas_keep_category_specific_whatsapp_links() -> None:
    labels = {
        "pretrial": "Проверить претензию",
        "response": "Проверить отзыв",
        "contract": "Проверить договор",
    }
    for kind, fragment in labels.items():
        markup = _document_review_markup(kind, "ru")
        button = markup.inline_keyboard[0][0]
        assert fragment in button.text
        assert button.url is not None
        assert button.url.startswith("https://wa.me/77005000553?text=")
        assert "отдельная платная услуга" in _document_review_text(kind, "ru")


def test_kazakh_claim_review_cta_is_paid_yes_no() -> None:
    text = _document_review_text("claim", "kk")
    assert "ақылы қызмет" in text
    assert "Қосымша заңгерлік қызметтер бөлек төленеді" in text
    markup = _document_review_markup("claim", "kk")
    yes_button, no_button = markup.inline_keyboard[0]
    assert yes_button.text == "✅ Иә"
    assert yes_button.url is not None
    assert "77005000553" in yes_button.url
    assert no_button.text == "❌ Жоқ"
    assert no_button.callback_data == "lawyer_review:claim:no"


def test_kazakh_other_review_ctas_remain_available() -> None:
    for kind in ("pretrial", "response", "contract"):
        markup = _document_review_markup(kind, "kk")
        button = markup.inline_keyboard[0][0]
        assert "WhatsApp" in button.text or "тексеру" in button.text
        assert button.url is not None
        assert "77005000553" in button.url
        assert "бөлек ақылы қызмет" in _document_review_text(kind, "kk")
