from __future__ import annotations

from korgan.config import Settings
from korgan.consultation_quota_bridge import polish_consultation_quota_notice


def _settings() -> Settings:
    return Settings(
        telegram_bot_token="123456:TEST_TOKEN",
        openai_api_key="test-openai",
        consultation_limit_enabled=True,
        free_consultations_per_day=5,
        consultation_price_kzt=1000,
    )


def test_fourth_free_consultation_warns_one_free_left_ru() -> None:
    text = polish_consultation_quota_notice(
        "🆓 Бесплатных консультаций сегодня осталось: 1.",
        _settings(),
    )
    assert "Осталась 1 бесплатная консультация" in text
    assert "4 из 5" in text
    assert "1 000 ₸" in text
    assert "каждый новый запрос" in text


def test_fifth_free_consultation_explains_next_request_is_paid_ru() -> None:
    text = polish_consultation_quota_notice(
        "🆓 Бесплатных консультаций сегодня осталось: 0.",
        _settings(),
    )
    assert "лимит консультаций на сегодня исчерпан" in text
    assert "5 из 5" in text
    assert "Следующий запрос будет стоить 1 000 ₸" in text


def test_fourth_free_consultation_warns_one_free_left_kk() -> None:
    text = polish_consultation_quota_notice(
        "🆓 Бүгін тегін кеңес қалды: 1.",
        _settings(),
    )
    assert "1 тегін кеңес қалды" in text
    assert "5 тегін кеңестің 4-ін" in text
    assert "1 000 ₸" in text


def test_unrelated_messages_are_not_changed() -> None:
    original = "Обычное сообщение KORGAN"
    assert polish_consultation_quota_notice(original, _settings()) == original
