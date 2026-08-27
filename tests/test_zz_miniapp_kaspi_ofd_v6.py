from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from korgan.config import Settings
from korgan.kaspi_ofd import (
    KaspiOFDVerificationError,
    canonicalize_kaspi_receipt_url,
    fiscal_receipt_issues,
    parse_kaspi_ofd_receipt,
)


ROOT = Path(__file__).resolve().parents[1]
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
      <div>{amount}</div>
      <div>№ чека</div><div>QR11577554266</div>
      <div>Дата и время</div><div>по Астане</div><div>27.08.2026 20:30</div>
      <div>Оплачено</div><div>{payment_method}</div>
      <div>ИИН/БИН продавца</div><div>123456789012</div>
      <div>РНМ</div><div>010103584359</div>
      <div>ФП</div><div>1548428246</div>
      <div>ОФД</div><div>Kaspi ОФД</div>
    </body></html>
    """.encode("utf-8")


def test_existing_railway_seller_bin_maps_into_payment_verifier() -> None:
    settings = Settings(
        telegram_bot_token="123456:TEST",
        openai_api_key="test-key",
        kaspi_seller_bin="123456789012",
    )
    assert settings.kaspi_payment_bin == "123456789012"
    assert settings.payment_seller_bin == "123456789012"


def test_live_kaspi_web_qr_is_normalized_to_official_download_endpoint() -> None:
    result = canonicalize_kaspi_receipt_url(WEB_URL)
    assert result.startswith("https://receipt.kaspi.kz/api/v3/receipt/download?")
    assert "extTranId=QR11577554266" in result
    assert "locale=ru" in result


def test_live_kaspi_fiscal_qr_shape_is_accepted() -> None:
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
def test_untrusted_receipt_urls_fail_closed(url: str) -> None:
    with pytest.raises(KaspiOFDVerificationError):
        canonicalize_kaspi_receipt_url(url)


def test_receipt_parser_extracts_strong_fiscal_identity() -> None:
    receipt = parse_kaspi_ofd_receipt(WEB_URL, _receipt_html())
    assert receipt.successful is True
    assert receipt.amount_kzt == 25_000
    assert receipt.receipt_number == "QR11577554266"
    assert receipt.seller_bin == "123456789012"
    assert receipt.rnm == "010103584359"
    assert receipt.fp == "1548428246"
    assert receipt.ofd_name == "Kaspi ОФД"
    assert receipt.payment_method == "с Kaspi Gold"
    assert receipt.transaction_id == "010103584359:QR11577554266:1548428246"


def test_exact_amount_bin_time_and_kaspi_method_pass() -> None:
    receipt = parse_kaspi_ofd_receipt(WEB_URL, _receipt_html())
    assert fiscal_receipt_issues(
        receipt,
        25_000,
        expected_recipient="OpenCourt (KORGAN)",
        expected_bin="123456789012",
        offered_at="2026-08-27T20:29:00+05:00",
        now=datetime(2026, 8, 27, 15, 35, tzinfo=timezone.utc),
    ) == []


def test_cash_receipt_wrong_bin_or_wrong_amount_never_unlocks() -> None:
    receipt = parse_kaspi_ofd_receipt(WEB_URL, _receipt_html(payment_method="Наличными"))
    issues = fiscal_receipt_issues(
        receipt,
        1_000,
        expected_bin="999999999999",
        offered_at="2026-08-27T20:40:00+05:00",
        now=datetime(2026, 8, 27, 15, 45, tzinfo=timezone.utc),
    )
    joined = " | ".join(issues)
    assert "через Kaspi" in joined
    assert "25000 ₸ вместо 1000 ₸" in joined
    assert "БИН продавца" in joined
    assert "до открытия" in joined


def test_v6_endpoint_has_no_ai_receipt_analyzer_or_file_upload_contract() -> None:
    source = (ROOT / "korgan" / "miniapp_api_v6.py").read_text(encoding="utf-8")
    assert "ReceiptAnalyzer" not in source
    assert "receipt_hard_issues" not in source
    assert "UploadFile" not in source
    assert '"ai_verification": False' in source
    assert '"ofd_verification": True' in source
    assert 'receipt_input": "fiscal_qr_url"' in source
    assert "fetch_kaspi_ofd_receipt" in source


def test_launcher_and_frontend_are_pinned_to_ofd_contract() -> None:
    launcher = (ROOT / "korgan" / "miniapp_telegram_launcher.py").read_text(encoding="utf-8")
    api = (ROOT / "miniapp" / "src" / "korganApiV2.js").read_text(encoding="utf-8")
    server = (ROOT / "miniapp" / "server.mjs").read_text(encoding="utf-8")
    ui = (ROOT / "miniapp" / "src" / "payment-ofd-copy.js").read_text(encoding="utf-8")
    index = (ROOT / "miniapp" / "index.html").read_text(encoding="utf-8")

    assert 'uvicorn.run("korgan.miniapp_api_v6:app"' in launcher
    assert "miniapp_api_v5:app" not in launcher
    assert "api_version !== '1.1.0'" in api
    assert "consultation_ai_receipt_verification !== false" in api
    assert "consultation_ofd_receipt_verification !== true" in api
    assert "document_ai_receipt_verification !== false" in api
    assert "document_ofd_receipt_verification !== true" in api
    assert "JSON.stringify({ qr_url: qrUrl })" in api
    assert "BarcodeDetector" in api
    assert "const API_BASE = '/korgan-api'" in api
    assert "KORGAN_API_PROXY_TARGET" in server
    assert "process.env.VITE_KORGAN_API_BASE" in server
    assert "delete headers.origin" in server
    assert "https.request" in server
    assert "AI не принимает решение об оплате" in ui
    assert "/src/payment-ofd-copy.js" in index
