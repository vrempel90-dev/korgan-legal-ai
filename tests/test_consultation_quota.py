from __future__ import annotations

from datetime import datetime, timezone

from korgan.config import Settings
from korgan.consultation_quota import (
    almaty_today,
    consultation_payment_markup,
    consultation_payment_text,
    receipt_fingerprint,
    strict_consultation_receipt_issues,
    verify_consultation_signature,
)
from korgan.consultation_quota_runtime import _parse_callback
from korgan.payment import ReceiptCheck


def _settings() -> Settings:
    return Settings(
        telegram_bot_token="123456:TEST_TOKEN",
        openai_api_key="test-openai",
        consultation_limit_enabled=True,
        free_consultations_per_day=5,
        consultation_price_kzt=1000,
        kaspi_payment_url="https://pay.kaspi.kz/pay/hk3wdvjz",
        database_url="postgresql://test:test@db/test",
    )


def _valid_receipt(**overrides) -> ReceiptCheck:
    data = dict(
        readable=True,
        looks_like_kaspi=True,
        payment_successful=True,
        amount_kzt=1000,
        date_time="18.08.2026 14:30",
        merchant_or_recipient="ИП Test",
        payer="Клиент",
        receipt_or_transaction_id="TX-12345",
        rnm="",
        fp="FP-123",
        suspicious_signals=(),
        notes=(),
    )
    data.update(overrides)
    return ReceiptCheck(**data)


def test_consultation_payment_offer_is_5_free_then_1000_and_url_hidden() -> None:
    settings = _settings()
    text = consultation_payment_text("ru", settings.free_consultations_per_day, settings.consultation_price_kzt)
    assert "5 из 5" in text
    assert "1 000 ₸" in text
    assert "pay.kaspi.kz" not in text
    assert "вопрос сохранён" in text.lower()
    assert "автоматической AI-проверки" in text

    markup = consultation_payment_markup(settings, user_id=12345, order_id=77, language="ru")
    pay_button = markup.inline_keyboard[0][0]
    paid_button = markup.inline_keyboard[1][0]
    assert pay_button.text == "💳 Оплатить через Kaspi"
    assert pay_button.url == settings.kaspi_payment_url
    assert paid_button.text == "✅ Я оплатил"
    assert paid_button.callback_data is not None
    assert len(paid_button.callback_data) <= 64


def test_consultation_payment_callback_is_signed_to_user_and_order() -> None:
    settings = _settings()
    markup = consultation_payment_markup(settings, user_id=12345, order_id=77, language="ru")
    callback_data = markup.inline_keyboard[1][0].callback_data
    assert callback_data is not None
    parsed = _parse_callback(callback_data, "proof")
    assert parsed is not None
    order_id, signature = parsed
    assert order_id == 77
    assert verify_consultation_signature(settings, signature, 12345, 77)
    assert not verify_consultation_signature(settings, signature, 54321, 77)
    assert not verify_consultation_signature(settings, signature, 12345, 78)


def test_valid_consultation_receipt_passes_strict_ai_policy() -> None:
    assert strict_consultation_receipt_issues(_valid_receipt(), 1000) == []


def test_consultation_receipt_rejects_wrong_amount_failed_or_suspicious() -> None:
    check = _valid_receipt(
        payment_successful=False,
        amount_kzt=900,
        suspicious_signals=("несовпадающий шрифт в сумме",),
    )
    issues = strict_consultation_receipt_issues(check, 1000)
    assert any("успешный платёж" in item for item in issues)
    assert any("900 ₸ вместо 1000 ₸" in item for item in issues)
    assert any("редактирования" in item for item in issues)


def test_consultation_receipt_requires_identifying_fields() -> None:
    check = _valid_receipt(date_time="", merchant_or_recipient="", receipt_or_transaction_id="", fp="")
    issues = strict_consultation_receipt_issues(check, 1000)
    assert any("дата и время" in item for item in issues)
    assert any("получатель" in item for item in issues)
    assert any("номер операции" in item for item in issues)


def test_receipt_fingerprint_blocks_same_bytes_by_design() -> None:
    first = receipt_fingerprint(b"same-kaspi-receipt")
    second = receipt_fingerprint(b"same-kaspi-receipt")
    other = receipt_fingerprint(b"another-receipt")
    assert first == second
    assert first != other
    assert len(first) == 64


def test_daily_limit_uses_kazakhstan_calendar_day() -> None:
    # 18 Aug 20:30 UTC is already 19 Aug 01:30 in Kazakhstan (UTC+5).
    now = datetime(2026, 8, 18, 20, 30, tzinfo=timezone.utc)
    assert almaty_today(now).isoformat() == "2026-08-19"


def test_kazakh_consultation_offer_has_same_limit_and_price() -> None:
    settings = _settings()
    text = consultation_payment_text("kk", 5, 1000)
    assert "5" in text
    assert "1 000 ₸" in text
    assert "pay.kaspi.kz" not in text
    markup = consultation_payment_markup(settings, 12345, 77, "kk")
    assert markup.inline_keyboard[0][0].url == settings.kaspi_payment_url
    assert markup.inline_keyboard[1][0].text == "✅ Төледім"
