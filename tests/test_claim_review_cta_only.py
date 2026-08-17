from aiogram.types import BufferedInputFile

from korgan.i18n import KK, RU
from korgan.localized_transport import (
    _claim_review_markup,
    _claim_review_text,
    _is_claim_document,
)


def _file(name: str) -> BufferedInputFile:
    return BufferedInputFile(b"test", filename=name)


def test_claim_helper_still_recognizes_only_claim() -> None:
    assert _is_claim_document(_file("KORGAN_iskovoe_zayavlenie.docx"))
    assert not _is_claim_document(_file("KORGAN_otzyv_na_isk.docx"))
    assert not _is_claim_document(_file("KORGAN_dogovor.docx"))
    assert not _is_claim_document(_file("KORGAN_dosudebnaya_pretenziya.docx"))


def test_russian_claim_cta_is_limited_to_this_claim_and_discloses_extra_payment() -> None:
    text = _claim_review_text(RU)
    assert "только к этому иску" in text.lower()
    assert "дополнительных документов" in text.lower()
    assert "платная услуга" in text.lower()
    assert "word/pdf" in text.lower()

    button = _claim_review_markup(RU).inline_keyboard[0][0]
    assert button.text == "👨‍⚖️ Проверить иск в WhatsApp"
    assert button.url is not None
    assert button.url.startswith("https://wa.me/77005000553?text=")


def test_kazakh_claim_cta_has_same_scope_and_whatsapp_number() -> None:
    text = _claim_review_text(KK)
    assert "тек осы талап қою арызына" in text.lower()
    assert "бөлек ақылы қызмет" in text.lower()
    assert "word/pdf" in text.lower()

    button = _claim_review_markup(KK).inline_keyboard[0][0]
    assert button.text == "👨‍⚖️ Талапты WhatsApp-та тексеру"
    assert button.url is not None
    assert button.url.startswith("https://wa.me/77005000553?text=")
