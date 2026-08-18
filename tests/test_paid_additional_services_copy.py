from korgan.i18n import KK, RU
from korgan.localized_transport import _document_review_text


def test_russian_review_copy_marks_additional_services_paid() -> None:
    text = _document_review_text("claim", RU)
    assert "Проверка платная." in text
    assert "Доп. услуги — платные." in text
    assert "Доп. услуги — отдельно." not in text


def test_kazakh_review_copy_marks_additional_services_paid() -> None:
    text = _document_review_text("claim", KK)
    assert "Тексеру ақылы." in text
    assert "Қосымша қызметтер ақылы." in text
