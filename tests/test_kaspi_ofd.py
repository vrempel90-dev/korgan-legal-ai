from __future__ import annotations

from datetime import datetime, timezone

import pytest

from korgan.kaspi_ofd import (
    KaspiOFDVerificationError,
    canonicalize_kaspi_receipt_url,
    fiscal_receipt_issues,
    parse_kaspi_ofd_receipt,
)
from korgan.payment_release_guard import can_release_paid_document


WEB_URL = (
    "https://receipt.kaspi.kz/web?extTranId=QR11577554266"
    "&sale_date=2026-08-27+20%3A30%3A00.000000%2B05%3A00"
)
FISCAL_URL = (
    "https://receipt.kaspi.kz/web/fiscal?f=010103584359&i=1548428246"
    "&s=25000.00&t=2026-08-27+20%3A30%3A00.000000%2B05%3A00"
)


def _receipt_html(*, payment_method: str = "с Kaspi Gold", amount: str = "25 000 ₸") -> bytes:
    return f"""
    <html><body>
      <h1>Фискальный чек</h1>
      <div>OpenCourt KORGAN</div>
      <div>ТОО OPENCOURT</div>
      <div>Платеж успешно совершен</div>
      <div>{amount}</div>
      <div>Продажа</div>
      <div>Юридическая услуга</div><div>1 шт. x {amount}</div>
      <div>№ чека</div><div>QR11577554266</div>
      <div>Дата и время</div><div>по Астане</div><div>27.08.2026 20:30</div>
      <div>Оплачено</div><div>{payment_method}</div>
      <div>ИИН/БИН продавца</div><div>123456789012</div>
      <div>РНМ</div><div>010103584359</div>
      <div>ФП</div><div>1548428246</div>
      <div>ОФД</div><div>Kaspi ОФД</div>
    </body></html>
    """.encode("utf-8")


def test_web_qr_is_normalized_to_official_download_endpoint() -> None:
    result = canonicalize_kaspi_receipt_url(WEB_URL)
    assert result.startswith("https://receipt.kaspi.kz/api/v3/receipt/download?")
    assert "extTranId=QR11577554266" in result
    assert "locale=ru" in result
    assert "sale_date=" in result


def test_fiscal_qr_shape_is_accepted_without_generic_url_fetching() -> None:
    result = canonicalize_kaspi_receipt_url(FISCAL_URL)
    assert result.startswith("https://receipt.kaspi.kz/web/fiscal?")
    assert "f=010103584359" in result
    assert "i=1548428246" in result
    assert "s=25000.00" in result


@pytest.mark.parametrize(
    "url",
    [
        "http://receipt.kaspi.kz/web?extTranId=x&sale_date=2026-08-27",
        "https://evil.example/web?extTranId=x&sale_date=2026-08-27",
        "https://receipt.kaspi.kz.evil.example/web?extTranId=x&sale_date=2026-08-27",
        "https://user@receipt.kaspi.kz/web?extTranId=x&sale_date=2026-08-27",
        "https://receipt.kaspi.kz/other?extTranId=x&sale_date=2026-08-27",
        "https://receipt.kaspi.kz/web?extTranId=x&sale_date=2026-08-27&next=https%3A%2F%2Fevil.example",
    ],
)
def test_untrusted_qr_targets_fail_closed(url: str) -> None:
    with pytest.raises(KaspiOFDVerificationError):
        canonicalize_kaspi_receipt_url(url)


def test_parser_extracts_fiscal_identity_amount_and_kaspi_payment_method() -> None:
    receipt = parse_kaspi_ofd_receipt(WEB_URL, _receipt_html())
    assert receipt.successful is True
    assert receipt.amount_kzt == 25_000
    assert receipt.receipt_number == "QR11577554266"
    assert receipt.sale_datetime == "27.08.2026 20:30"
    assert receipt.seller_bin == "123456789012"
    assert receipt.rnm == "010103584359"
    assert receipt.fp == "1548428246"
    assert receipt.ofd_name == "Kaspi ОФД"
    assert receipt.payment_method == "с Kaspi Gold"
    assert receipt.transaction_id == "010103584359:QR11577554266:1548428246"


def test_fiscal_query_amount_is_used_only_after_official_receipt_content_is_parsed() -> None:
    receipt = parse_kaspi_ofd_receipt(FISCAL_URL, _receipt_html(amount="1 000 ₸"))
    assert receipt.amount_kzt == 25_000
    assert receipt.rnm == "010103584359"
    assert receipt.fp == "1548428246"


def test_exact_amount_bin_time_and_kaspi_method_pass() -> None:
    receipt = parse_kaspi_ofd_receipt(WEB_URL, _receipt_html())
    issues = fiscal_receipt_issues(
        receipt,
        25_000,
        expected_recipient="OpenCourt (KORGAN)",
        expected_bin="123456789012",
        offered_at="2026-08-27T20:29:00+05:00",
        now=datetime(2026, 8, 27, 15, 35, tzinfo=timezone.utc),
    )
    assert issues == []


def test_cash_fiscal_receipt_does_not_unlock_kaspi_payment() -> None:
    receipt = parse_kaspi_ofd_receipt(WEB_URL, _receipt_html(payment_method="Наличными"))
    issues = fiscal_receipt_issues(
        receipt,
        25_000,
        expected_bin="123456789012",
        offered_at="2026-08-27T20:29:00+05:00",
        now=datetime(2026, 8, 27, 15, 35, tzinfo=timezone.utc),
    )
    assert any("через Kaspi" in issue for issue in issues)


def test_wrong_amount_bin_or_old_receipt_fail_closed() -> None:
    receipt = parse_kaspi_ofd_receipt(WEB_URL, _receipt_html())
    issues = fiscal_receipt_issues(
        receipt,
        1_000,
        expected_bin="999999999999",
        offered_at="2026-08-27T20:40:00+05:00",
        now=datetime(2026, 8, 27, 15, 45, tzinfo=timezone.utc),
    )
    joined = " | ".join(issues)
    assert "25000 ₸ вместо 1000 ₸" in joined
    assert "БИН продавца" in joined
    assert "до открытия" in joined


def test_ofd_release_guard_is_explicit_and_legacy_ai_reason_stays_stable() -> None:
    ofd = can_release_paid_document(
        kind="claim",
        receipt_submitted=True,
        receipt_precheck_passed=True,
        ofd_verified=True,
    )
    assert ofd.allowed is True
    assert ofd.reason == "payment_kaspi_ofd_verified"

    legacy = can_release_paid_document(
        kind="claim",
        receipt_submitted=True,
        receipt_precheck_passed=True,
        ai_verified=True,
    )
    assert legacy.allowed is True
    assert legacy.reason == "payment_ai_verified"
