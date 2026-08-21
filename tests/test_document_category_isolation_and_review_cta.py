from __future__ import annotations

import asyncio
from types import SimpleNamespace

from aiogram.types import BufferedInputFile

from korgan.document_category_router import PreferredDocumentCategory, preferred_document_category
from korgan.localized_transport import (
    _claim_client_caption,
    _document_caption_with_review,
    _document_client_caption,
    _document_review_markup,
    _document_review_text,
    _generated_document_kind,
)
from korgan.pretrial_response import is_pretrial_response_request
from korgan.review_cta_runtime import _decline_text


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


def test_pretrial_response_is_its_own_category() -> None:
    assert preferred_document_category("Подготовь ответ на досудебную претензию поставщика.") == "pretrial_response"
    assert preferred_document_category("Составь ответ на претензию о взыскании 600 000 тенге.") == "pretrial_response"
    assert is_pretrial_response_request("Подготовь ответ на претензию поставщика.") is True


def test_pretrial_response_never_becomes_outgoing_pretrial_or_court_response() -> None:
    assert preferred_document_category("Подготовь досудебную претензию должнику.") == "pretrial"
    assert preferred_document_category("Подготовь отзыв на исковое заявление истца.") == "response"
    assert preferred_document_category("Подготовь ответ на исковое заявление истца.") == "response"
    assert is_pretrial_response_request("Подготовь отзыв на исковое заявление истца.") is False
    assert is_pretrial_response_request("Подготовь досудебную претензию должнику.") is False


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
    assert preferred_document_category("Сотқа дейінгі талапқа жауапты дайында.") == "pretrial_response"
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


def test_generated_document_kind_is_exact_for_all_five_categories() -> None:
    expected = {
        "KORGAN_iskovoe_zayavlenie.docx": "claim",
        "KORGAN_dosudebnaya_pretenziya.docx": "pretrial",
        "KORGAN_sotqa_deyingi_talap.docx": "pretrial",
        "KORGAN_otvet_na_pretenziyu.docx": "pretrial_response",
        "KORGAN_sotqa_deyingi_talapqa_zhauap.docx": "pretrial_response",
        "KORGAN_otzyv_na_isk.docx": "response",
        "KORGAN_dogovor.docx": "contract",
    }
    for filename, kind in expected.items():
        document = BufferedInputFile(b"test", filename=filename)
        assert _generated_document_kind(document) == kind

    assert _generated_document_kind(BufferedInputFile(b"test", filename="random.docx")) is None


def test_every_review_cta_is_small_paid_yes_no_and_link_is_only_in_yes_button() -> None:
    expected = {
        "claim": "Рекомендуем проверить иск у профессионального юриста",
        "pretrial": "Рекомендуем проверить досудебную претензию у профессионального юриста",
        "pretrial_response": "Рекомендуем проверить ответ на претензию у профессионального юриста",
        "response": "Рекомендуем проверить отзыв на иск у профессионального юриста",
        "contract": "Рекомендуем проверить договор у профессионального юриста",
    }

    for kind, document_fragment in expected.items():
        text = _document_review_text(kind, "ru")
        assert document_fragment in text
        assert "Проверка платная. Доп. услуги — платные." in text
        assert "Передать юристу?" in text
        assert "http" not in text
        assert "wa.me" not in text
        assert len(text) < 220
        assert "KORGAN QUALITY" not in text
        assert "PRELIMINARY" not in text

        markup = _document_review_markup(kind, "ru")
        assert len(markup.inline_keyboard) == 1
        assert len(markup.inline_keyboard[0]) == 2
        yes_button, no_button = markup.inline_keyboard[0]
        assert yes_button.text == "✅ Да"
        assert yes_button.url == "https://wa.me/77005000553"
        assert no_button.text == "❌ Нет"
        assert no_button.url is None
        assert no_button.callback_data == f"lawyer_review:{kind}:no"


def test_document_caption_contains_compact_review_cta_on_same_message() -> None:
    for kind in ("claim", "pretrial", "pretrial_response", "response", "contract"):
        caption = _document_caption_with_review(kind, "ru")
        assert _document_client_caption(kind, "ru") in caption
        assert _document_review_text(kind, "ru") in caption
        assert "PRELIMINARY" not in caption
        assert "KORGAN QUALITY" not in caption
        assert "wa.me" not in caption
        assert len(caption) < 1024


def test_every_generated_document_caption_hides_internal_quality_diagnostics() -> None:
    expected_ru = {
        "claim": "✅ Иск сформирован в Word (.docx).",
        "pretrial": "✅ Досудебная претензия сформирована в Word (.docx).",
        "pretrial_response": "✅ Ответ на претензию сформирован в Word (.docx).",
        "response": "✅ Отзыв на иск сформирован в Word (.docx).",
        "contract": "✅ Договор сформирован в Word (.docx).",
    }
    for kind, expected in expected_ru.items():
        caption = _document_client_caption(kind, "ru")
        assert caption == expected
        assert "QUALITY" not in caption
        assert "PRELIMINARY" not in caption

    assert _claim_client_caption("ru") == expected_ru["claim"]
    assert _claim_client_caption("kk") == "✅ Талап қою арызы Word (.docx) форматында дайын."


def test_kazakh_review_cta_is_compact_and_link_is_hidden_in_yes_button() -> None:
    for kind in ("claim", "pretrial", "pretrial_response", "response", "contract"):
        text = _document_review_text(kind, "kk")
        assert "Тексеру ақылы. Қосымша қызметтер ақылы." in text
        assert "http" not in text
        assert "wa.me" not in text
        assert len(text) < 220
        caption = _document_caption_with_review(kind, "kk")
        assert _document_client_caption(kind, "kk") in caption
        assert text in caption
        markup = _document_review_markup(kind, "kk")
        yes_button, no_button = markup.inline_keyboard[0]
        assert yes_button.text == "✅ Иә"
        assert yes_button.url == "https://wa.me/77005000553"
        assert no_button.text == "❌ Жоқ"
        assert no_button.url is None
        assert no_button.callback_data == f"lawyer_review:{kind}:no"


def test_decline_copy_is_specific_for_each_document_category() -> None:
    assert "Иск" in _decline_text("claim", "ru")
    assert "Досудебная претензия" in _decline_text("pretrial", "ru")
    assert "Ответ на претензию" in _decline_text("pretrial_response", "ru")
    assert "Отзыв на иск" in _decline_text("response", "ru")
    assert "Договор" in _decline_text("contract", "ru")
    for kind in ("claim", "pretrial", "pretrial_response", "response", "contract"):
        assert _decline_text(kind, "kk").startswith("Түсінікті.")
