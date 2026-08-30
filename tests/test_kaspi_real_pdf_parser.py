from __future__ import annotations

from korgan.miniapp_api_ofd_upload import (
    _assert_qr_matches_uploaded_receipt,
    _parse_uploaded_pdf_text,
)


FISCAL_URL = (
    "https://receipt.kaspi.kz/web/fiscal?"
    "i=557225556134&f=010103806424&s=1000.0&"
    "t=2026-08-27%2018%3A18%3A22.168302"
)

REALISTIC_KASPI_PDF_TEXT = """
Фискальный чек
Оплата совершена
1 000 ₸
YSA education на Кунаева
ИП YSA EDUCATION
Продажа
Обработка данных и генерация документа
1шт.x1 000₸ 1 000 ₸
№ чека QR17262148385
Дата и время
по Астане
27.08.2026 18:18
Оплачено с Kaspi Gold
Адрес г. Астана, Кунаева, 29/1
ИИН/БИН продавца 820608350657
ФИО покупателя Клиент К.
РНМ 010103806424
ЗНМ KK4160038097
ФП 557225556134
ОФД Kaspi ОФД
"""


def test_real_kaspi_pdf_layout_is_parsed_without_korgan_brand_name() -> None:
    receipt = _parse_uploaded_pdf_text(
        REALISTIC_KASPI_PDF_TEXT,
        FISCAL_URL,
        body_sha256="a" * 64,
    )
    assert receipt is not None
    assert receipt.successful is True
    assert receipt.amount_kzt == 1000
    assert receipt.receipt_number == "QR17262148385"
    assert receipt.sale_datetime == "27.08.2026 18:18"
    assert receipt.seller_name == "ИП YSA EDUCATION"
    assert receipt.seller_bin == "820608350657"
    assert receipt.rnm == "010103806424"
    assert receipt.fp == "557225556134"
    assert receipt.ofd_name == "Kaspi ОФД"
    assert receipt.payment_method == "с Kaspi Gold"
    assert "ЗНМ KK4160038097" in receipt.raw_text
    _assert_qr_matches_uploaded_receipt(FISCAL_URL, receipt)


def test_address_is_not_required_for_payment_verification() -> None:
    receipt = _parse_uploaded_pdf_text(
        REALISTIC_KASPI_PDF_TEXT.replace("Адрес г. Астана, Кунаева, 29/1\n", ""),
        FISCAL_URL,
        body_sha256="b" * 64,
    )
    assert receipt is not None
    assert receipt.successful is True


def test_pdf_and_qr_amount_mismatch_fails_closed() -> None:
    receipt = _parse_uploaded_pdf_text(
        REALISTIC_KASPI_PDF_TEXT.replace("Оплата совершена\n1 000 ₸", "Оплата совершена\n2 000 ₸"),
        FISCAL_URL,
        body_sha256="c" * 64,
    )
    assert receipt is not None
    try:
        _assert_qr_matches_uploaded_receipt(FISCAL_URL, receipt)
    except Exception as exc:
        assert "Сумма" in str(exc)
    else:
        raise AssertionError("QR/PDF amount mismatch must fail")
