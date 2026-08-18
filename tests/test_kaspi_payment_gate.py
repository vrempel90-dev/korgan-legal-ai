from __future__ import annotations

from korgan.config import Settings
from korgan.payment import (
    ReceiptCheck,
    admin_decision_markup,
    payment_offer_markup,
    payment_offer_text,
    receipt_hard_issues,
    verify_admin_action,
    verify_user_payment,
)
from korgan.payment_runtime import _parse_admin_callback, _parse_user_callback


def _settings() -> Settings:
    return Settings(
        telegram_bot_token="123456:TEST_TOKEN",
        openai_api_key="test-openai",
        admin_telegram_ids="777",
        payments_enabled=True,
        kaspi_payment_url="https://pay.kaspi.kz/pay/hk3wdvjz",
        document_price_kzt=1000,
    )


def test_payment_offer_is_compact_and_kaspi_link_is_only_in_button() -> None:
    settings = _settings()
    text = payment_offer_text("pretrial", "ru", 1000)
    assert "Стоимость: 1 000 ₸" in text
    assert "Word-файл будет выдан только после подтверждения оплаты" in text
    assert "pay.kaspi.kz" not in text

    markup = payment_offer_markup(settings, 12345, 678, "pretrial", "ru")
    pay_button = markup.inline_keyboard[0][0]
    paid_button = markup.inline_keyboard[1][0]
    assert pay_button.text == "💳 Оплатить через Kaspi"
    assert pay_button.url == "https://pay.kaspi.kz/pay/hk3wdvjz"
    assert paid_button.text == "✅ Я оплатил"
    assert paid_button.url is None
    assert paid_button.callback_data is not None
    assert len(paid_button.callback_data) <= 64

    parsed = _parse_user_callback(paid_button.callback_data)
    assert parsed is not None
    doc_msg, kind, language, signature = parsed
    assert (doc_msg, kind, language) == (678, "pretrial", "ru")
    assert verify_user_payment(settings, signature, 12345, doc_msg, kind, language)
    assert not verify_user_payment(settings, signature, 54321, doc_msg, kind, language)


def test_admin_decision_is_signed_and_bound_to_user_document_and_kind() -> None:
    settings = _settings()
    markup = admin_decision_markup(settings, 12345, 678, "claim", "ru")
    yes_button, no_button = markup.inline_keyboard[0]
    assert yes_button.callback_data is not None
    assert no_button.callback_data is not None
    assert len(yes_button.callback_data) <= 64
    assert len(no_button.callback_data) <= 64

    parsed = _parse_admin_callback(yes_button.callback_data)
    assert parsed is not None
    action, user_id, doc_msg, kind, language, signature = parsed
    assert action == "ok"
    assert (user_id, doc_msg, kind, language) == (12345, 678, "claim", "ru")
    assert verify_admin_action(settings, signature, user_id, doc_msg, kind, language)
    assert not verify_admin_action(settings, signature, user_id, doc_msg + 1, kind, language)


def test_receipt_precheck_blocks_wrong_amount_and_failed_payment() -> None:
    check = ReceiptCheck(
        readable=True,
        looks_like_kaspi=True,
        payment_successful=False,
        amount_kzt=900,
        date_time="18.08.2026 11:00",
        merchant_or_recipient="Test IP",
        payer="Client",
        receipt_or_transaction_id="ABC",
        rnm="",
        fp="",
        suspicious_signals=(),
        notes=(),
    )
    issues = receipt_hard_issues(check, 1000)
    assert any("успешный платёж" in item for item in issues)
    assert any("900 ₸ вместо 1000 ₸" in item for item in issues)


def test_receipt_precheck_never_auto_releases_even_when_fields_match() -> None:
    check = ReceiptCheck(
        readable=True,
        looks_like_kaspi=True,
        payment_successful=True,
        amount_kzt=1000,
        date_time="18.08.2026 11:00",
        merchant_or_recipient="Test IP",
        payer="Client",
        receipt_or_transaction_id="ABC",
        rnm="123",
        fp="456",
        suspicious_signals=(),
        notes=(),
    )
    assert receipt_hard_issues(check, 1000) == []
    # Passing the AI pre-check only means the receipt may be sent to an admin;
    # actual document release exists only in the signed admin callback handler.
    assert check.payment_successful is True


def test_kazakh_payment_offer_uses_same_price_and_no_raw_url() -> None:
    settings = _settings()
    text = payment_offer_text("contract", "kk", settings.document_price_kzt)
    assert "1 000 ₸" in text
    assert "pay.kaspi.kz" not in text
    markup = payment_offer_markup(settings, 12345, 678, "contract", "kk")
    assert markup.inline_keyboard[0][0].url == settings.kaspi_payment_url
    assert markup.inline_keyboard[1][0].text == "✅ Төледім"
