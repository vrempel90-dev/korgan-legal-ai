from __future__ import annotations

import asyncio
from types import SimpleNamespace

from aiogram.types import BufferedInputFile

from korgan.document_category_router import PreferredDocumentCategory, preferred_document_category
from korgan.localized_transport import (
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


def test_review_cta_is_category_specific_and_points_to_lawyer_whatsapp() -> None:
    labels = {
        "claim": "Проверить иск",
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


def test_kazakh_review_cta_exists_for_every_category() -> None:
    for kind in ("claim", "pretrial", "response", "contract"):
        markup = _document_review_markup(kind, "kk")
        button = markup.inline_keyboard[0][0]
        assert "WhatsApp" in button.text or "тексеру" in button.text
        assert button.url is not None
        assert "77005000553" in button.url
        assert "бөлек ақылы қызмет" in _document_review_text(kind, "kk")
