from __future__ import annotations

from korgan.pretrial import is_pretrial_request
from korgan.pretrial_response import is_pretrial_response_request
from korgan.response_intent import is_response_to_claim_request
from korgan.ui import documents_menu


def test_answer_to_pretension_belongs_only_to_its_own_intent() -> None:
    text = "Подготовь ответ на досудебную претензию поставщика"
    assert is_pretrial_response_request(text) is True
    assert is_pretrial_request(text) is False
    assert is_response_to_claim_request(text) is False


def test_outgoing_pretension_stays_outgoing_pretension() -> None:
    text = "Подготовь досудебную претензию должнику"
    assert is_pretrial_request(text) is True
    assert is_pretrial_response_request(text) is False
    assert is_response_to_claim_request(text) is False


def test_court_response_stays_response_to_claim() -> None:
    text = "Подготовь отзыв на исковое заявление истца"
    assert is_response_to_claim_request(text) is True
    assert is_pretrial_response_request(text) is False
    assert is_pretrial_request(text) is False


def test_document_menu_has_distinct_callbacks_for_both_responses() -> None:
    ru = documents_menu("ru")
    buttons = {button.text: button.callback_data for row in ru.inline_keyboard for button in row}
    assert buttons["📨 Досудебная претензия"] == "doc:pretrial"
    assert buttons["↩️ Ответ на претензию"] == "doc:pretrial_response"
    assert buttons["🛡 Отзыв на иск"] == "doc:response"

    kk = documents_menu("kk")
    buttons_kk = {button.text: button.callback_data for row in kk.inline_keyboard for button in row}
    assert buttons_kk["📨 Сотқа дейінгі талап"] == "doc:pretrial"
    assert buttons_kk["↩️ Сотқа дейінгі талапқа жауап"] == "doc:pretrial_response"
    assert buttons_kk["🛡 Талапқа пікір"] == "doc:response"
