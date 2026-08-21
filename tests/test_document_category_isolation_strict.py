from korgan.document_category_router import preferred_document_category
from korgan.ui import documents_menu


def _button_texts(markup) -> list[str]:
    return [button.text for row in markup.inline_keyboard for button in row]


def test_each_russian_document_request_has_one_owner() -> None:
    assert preferred_document_category("Подготовь исковое заявление по договору поставки") == "claim"
    assert preferred_document_category("Подготовь отзыв на исковое заявление") == "response"
    assert preferred_document_category("Подготовь досудебную претензию") == "pretrial"
    assert preferred_document_category("Подготовь ответ на досудебную претензию") == "pretrial_response"
    assert preferred_document_category("Составь возражение на претензию контрагента") == "pretrial_response"


def test_old_mixed_term_is_not_silently_routed() -> None:
    assert preferred_document_category("Подготовь отзыв на претензию") is None
    assert preferred_document_category("Составь отзыв на досудебную претензию") is None


def test_documents_menu_keeps_claim_response_and_pretrial_response_separate() -> None:
    texts = _button_texts(documents_menu("ru"))
    assert "🛡 Ответ на претензию" in texts
    assert "🛡 Отзыв на иск" in texts
    assert texts.index("🛡 Ответ на претензию") != texts.index("🛡 Отзыв на иск")


def test_pretrial_response_callback_stays_distinct_from_claim_response() -> None:
    menu = documents_menu("ru")
    callbacks = {button.text: button.callback_data for row in menu.inline_keyboard for button in row}
    assert callbacks["🛡 Ответ на претензию"] == "doc:pretrial_response"
    assert callbacks["🛡 Отзыв на иск"] == "doc:response"
