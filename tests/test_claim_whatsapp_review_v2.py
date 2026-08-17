from __future__ import annotations

from urllib.parse import unquote

from korgan.claim_review_handoff import (
    LAWYER_WHATSAPP_NUMBER,
    build_media_template_payload,
    claim_review_consent_markup,
    claim_review_consent_text,
    claim_review_offer_markup,
    claim_review_offer_text,
    discard_claim_review,
    is_claim_review_document,
    lawyer_chat_markup,
    lawyer_chat_url,
    pending_claim_for_review,
    register_claim_for_review,
)
from korgan.config import Settings
from korgan.i18n import KK, RU


def _settings(**overrides: str) -> Settings:
    values = {
        "telegram_bot_token": "123:telegram",
        "openai_api_key": "sk-test",
        "whatsapp_access_token": "meta-token",
        "whatsapp_phone_number_id": "123456789",
        "whatsapp_graph_api_version": "v99.0",
        "whatsapp_review_template_name": "korgan_claim_review_request",
        "whatsapp_review_template_language": "ru",
        "whatsapp_lawyer_number": LAWYER_WHATSAPP_NUMBER,
    }
    values.update(overrides)
    return Settings(**values)


def test_review_is_only_for_generated_claim_file() -> None:
    assert is_claim_review_document("KORGAN_iskovoe_zayavlenie.docx")
    assert not is_claim_review_document("KORGAN_dosudebnaya_pretenziya.docx")
    assert not is_claim_review_document("KORGAN_otzyv_na_isk.docx")
    assert not is_claim_review_document("KORGAN_dogovor.docx")
    assert not is_claim_review_document("client_claim.docx")


def test_offer_warns_about_ai_and_separate_payment_for_extra_documents() -> None:
    text = claim_review_offer_text(RU)
    assert "искусственного интеллекта" in text
    assert "ошибки или неточности" in text
    assert "только к этому иску" in text
    assert "дополнительные документы" in text
    assert "оплачивается отдельно" in text
    markup = claim_review_offer_markup(RU)
    assert markup.inline_keyboard[0][0].callback_data == "claimreview:offer"
    assert markup.inline_keyboard[1][0].callback_data == "claimreview:cancel"


def test_consent_is_explicit_and_limited_to_this_claim() -> None:
    text = claim_review_consent_text(RU)
    assert "Согласие на передачу данных" in text
    assert "тот Word-файл иска, который был выдан вам" in text
    assert "исключительно" in text
    assert "проверки данного иска" in text
    assert "Дополнительные документы" in text
    assert "оплачиваются отдельно" in text
    assert "не означает заключение договора" in text
    markup = claim_review_consent_markup(RU)
    assert markup.inline_keyboard[0][0].callback_data == "claimreview:confirm"


def test_whatsapp_link_is_pretty_button_to_exact_lawyer_number_with_reference() -> None:
    reference = "KORGAN-A1B2C3"
    url = lawyer_chat_url(reference, RU)
    assert url.startswith("https://wa.me/77005000553?text=")
    assert reference in unquote(url)
    markup = lawyer_chat_markup(reference, RU)
    button = markup.inline_keyboard[0][0]
    assert button.text == "💬 Открыть чат с юристом"
    assert button.url == url


def test_pending_cache_keeps_exact_file_and_reference() -> None:
    chat_id = 998877
    discard_claim_review(chat_id)
    item = register_claim_for_review(chat_id, b"exact-docx-bytes", "KORGAN_iskovoe_zayavlenie.docx", RU)
    stored = pending_claim_for_review(chat_id)
    assert stored is item
    assert stored is not None
    assert stored.data == b"exact-docx-bytes"
    assert stored.reference.startswith("KORGAN-")
    discard_claim_review(chat_id)
    assert pending_claim_for_review(chat_id) is None


def test_whatsapp_template_payload_sends_document_to_configured_lawyer() -> None:
    settings = _settings()
    payload = build_media_template_payload(settings, "media-123", "KORGAN-A1B2C3_isk_na_proverku.docx")
    assert payload["to"] == "77005000553"
    assert payload["type"] == "template"
    assert payload["template"]["name"] == "korgan_claim_review_request"
    document = payload["template"]["components"][0]["parameters"][0]["document"]
    assert document["id"] == "media-123"
    assert document["filename"] == "KORGAN-A1B2C3_isk_na_proverku.docx"


def test_whatsapp_review_is_fail_closed_until_all_meta_settings_exist() -> None:
    assert _settings().whatsapp_review_ready
    assert not _settings(whatsapp_access_token="").whatsapp_review_ready
    assert not _settings(whatsapp_phone_number_id="").whatsapp_review_ready
    assert not _settings(whatsapp_graph_api_version="").whatsapp_review_ready
    assert not _settings(whatsapp_review_template_name="").whatsapp_review_ready


def test_kazakh_review_copy_and_buttons_exist() -> None:
    assert "жасанды интеллект" in claim_review_offer_text(KK)
    assert "бөлек төленеді" in claim_review_consent_text(KK)
    assert claim_review_offer_markup(KK).inline_keyboard[0][0].text.startswith("👨‍⚖️")
    assert lawyer_chat_markup("KORGAN-ABC123", KK).inline_keyboard[0][0].url is not None
