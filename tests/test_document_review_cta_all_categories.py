from aiogram.types import BufferedInputFile

from korgan.i18n import KK, RU
from korgan.localized_transport import (
    _document_review_markup,
    _document_review_text,
    _generated_document_kind,
)


def _file(name: str) -> BufferedInputFile:
    return BufferedInputFile(b"test", filename=name)


def test_all_current_document_categories_receive_review_cta() -> None:
    assert _generated_document_kind(_file("KORGAN_iskovoe_zayavlenie.docx")) == "claim"
    assert _generated_document_kind(_file("KORGAN_dosudebnaya_pretenziya.docx")) == "pretrial"
    assert _generated_document_kind(_file("KORGAN_sotqa_deyingi_talap.docx")) == "pretrial"
    assert _generated_document_kind(_file("KORGAN_otzyv_na_isk.docx")) == "response"
    assert _generated_document_kind(_file("KORGAN_dogovor.docx")) == "contract"


def test_future_korgan_document_gets_safe_generic_cta() -> None:
    assert _generated_document_kind(_file("KORGAN_zhaloba.docx")) == "document"
    assert _generated_document_kind(_file("KORGAN_other.pdf")) == "document"
    assert _generated_document_kind(_file("client_upload.docx")) is None


def test_russian_cta_is_specific_and_discloses_extra_payment_for_every_category() -> None:
    expected = {
        "claim": "Проверить иск в WhatsApp",
        "pretrial": "Проверить претензию в WhatsApp",
        "response": "Проверить отзыв в WhatsApp",
        "contract": "Проверить договор в WhatsApp",
        "document": "Проверить документ в WhatsApp",
    }
    for kind, label in expected.items():
        text = _document_review_text(kind, RU).lower()
        assert "только к этому" in text or "только к этой" in text
        assert "дополнительных документов" in text
        assert "отдельная платная услуга" in text
        button = _document_review_markup(kind, RU).inline_keyboard[0][0]
        assert label in button.text
        assert button.url is not None
        assert button.url.startswith("https://wa.me/77005000553?text=")


def test_kazakh_cta_has_same_scope_and_payment_disclosure() -> None:
    for kind in ("claim", "pretrial", "response", "contract", "document"):
        text = _document_review_text(kind, KK).lower()
        assert "тексеру тек осы" in text
        assert "бөлек ақылы қызмет" in text
        button = _document_review_markup(kind, KK).inline_keyboard[0][0]
        assert button.url is not None
        assert button.url.startswith("https://wa.me/77005000553?text=")
