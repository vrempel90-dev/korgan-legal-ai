from __future__ import annotations

import asyncio

from korgan.config import Settings
from korgan.consultation_ui_runtime import consultation_prompt_text, prices_text
import korgan.consultation_quota_bridge as bridge


def _settings(*, enabled: bool = True) -> Settings:
    return Settings(
        telegram_bot_token="123456:TEST_TOKEN",
        openai_api_key="test-openai",
        payments_enabled=True,
        kaspi_payment_url="https://pay.kaspi.kz/pay/hk3wdvjz",
        document_price_kzt=1000,
        consultation_limit_enabled=enabled,
        free_consultations_per_day=5,
        consultation_price_kzt=1000,
        database_url="postgresql://test:test@localhost:5432/test",
    )


def test_consultation_prompt_ru_and_kk_show_daily_quota_when_enabled() -> None:
    settings = _settings()
    ru = consultation_prompt_text("ru", settings)
    kk = consultation_prompt_text("kk", settings)

    assert "Первые 5 консультаций в сутки бесплатно" in ru
    assert "1 000 ₸" in ru
    assert "алғашқы 5 кеңес тегін" in kk
    assert "1 000 ₸" in kk


def test_prices_show_active_kaspi_documents_and_consultation_tariff() -> None:
    settings = _settings()
    ru = prices_text("ru", settings)
    kk = prices_text("kk", settings)

    assert "Первые 5 запросов в сутки — бесплатно" in ru
    assert "Далее каждый запрос — 1 000 ₸" in ru
    assert "Оплата документов — через Kaspi" in ru
    assert "оплата временно отключена" not in ru.lower()
    assert "Күніне алғашқы 5 сұрау — тегін" in kk
    assert "Одан кейін әр сұрау — 1 000 ₸" in kk
    assert "Kaspi арқылы төленеді" in kk
    assert "pay.kaspi.kz" not in ru
    assert "pay.kaspi.kz" not in kk


def test_quota_disabled_does_not_advertise_consultation_tariff() -> None:
    settings = _settings(enabled=False)
    assert "Первые 5 консультаций" not in consultation_prompt_text("ru", settings)
    assert "Күніне алғашқы 5" not in consultation_prompt_text("kk", settings)
    assert "⚖️ Консультации" not in prices_text("ru", settings)
    assert "⚖️ Кеңес беру" not in prices_text("kk", settings)


def test_kazakh_legal_filter_yields_to_quota_when_enabled(monkeypatch) -> None:
    settings = _settings(enabled=True)
    monkeypatch.setattr(bridge, "get_settings", lambda: settings)
    bridge.install_consultation_quota_bridge()

    result = asyncio.run(bridge.KazakhLegalText().__call__(object(), object()))
    assert result is False
