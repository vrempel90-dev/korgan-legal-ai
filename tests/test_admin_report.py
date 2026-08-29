from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from korgan.admin import admin_main_keyboard, is_admin
from korgan.admin_report import AdminReportMetrics, format_admin_report, next_admin_report_at
from korgan.config import Settings

ALMATY = ZoneInfo("Asia/Almaty")


def _settings(**overrides) -> Settings:
    values = {
        "telegram_bot_token": "telegram-secret",
        "openai_api_key": "openai-secret",
        "admin_telegram_ids": "1001",
        "admin_report_telegram_id": "6954213997",
        "document_price_kzt": 1000,
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def test_report_recipient_does_not_receive_admin_privileges() -> None:
    settings = _settings()

    assert settings.admin_report_id == 6954213997
    assert is_admin(1001, settings)
    assert not is_admin(6954213997, settings)


def test_report_button_is_exposed_in_admin_namespace() -> None:
    callbacks = [
        button.callback_data
        for row in admin_main_keyboard().inline_keyboard
        for button in row
        if button.callback_data is not None
    ]

    assert "admin:report" in callbacks


def test_report_contains_only_real_aggregate_labels_and_revenue() -> None:
    settings = _settings()
    metrics = AdminReportMetrics(
        free_consultations=4,
        consultation_users=2,
        paid_consultations=1,
        consultation_revenue_kzt=1000,
        agent_document_payments=2,
        agent_document_users=2,
        miniapp_documents=3,
        miniapp_document_users=3,
        miniapp_document_revenue_kzt=3000,
    )
    now = datetime(2026, 8, 29, 14, 30, tzinfo=ALMATY)

    report = format_admin_report(settings, metrics, now=now)

    assert "29.08.2026" in report
    assert "Бесплатных использовано: 4" in report
    assert "подтверждено оплат через Kaspi ОФД: 2" in report
    assert "Mini App: оплаченных документов завершено: 3" in report
    assert "Подтверждённая выручка по сохранённым суммам: 4 000 ₸" in report
    assert "legacy anti-replay хранит факт оплаты без суммы" in report
    assert settings.telegram_bot_token not in report
    assert settings.openai_api_key not in report


def test_next_report_is_21_almaty_and_never_runs_twice_same_slot() -> None:
    before = datetime(2026, 8, 29, 20, 30, tzinfo=ALMATY)
    target = next_admin_report_at(before, 21)
    assert target == datetime(2026, 8, 29, 21, 0, tzinfo=ALMATY)

    at_slot = datetime(2026, 8, 29, 21, 0, tzinfo=ALMATY)
    next_day = next_admin_report_at(at_slot, 21)
    assert next_day == at_slot + timedelta(days=1)


def test_invalid_report_recipient_fails_closed() -> None:
    settings = _settings(admin_report_telegram_id="not-a-number")
    assert settings.admin_report_id is None
