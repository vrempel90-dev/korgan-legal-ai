from __future__ import annotations

from korgan.admin import admin_home_text, admin_main_keyboard, admin_page, is_admin
from korgan.config import Settings


def _settings(admin_ids: str = "1001,2002") -> Settings:
    return Settings(
        telegram_bot_token="telegram-secret",
        openai_api_key="openai-secret",
        admin_telegram_ids=admin_ids,
        _env_file=None,
    )


def test_only_configured_telegram_ids_are_admins() -> None:
    settings = _settings()

    assert is_admin(1001, settings)
    assert is_admin(2002, settings)
    assert not is_admin(3003, settings)
    assert not is_admin(None, settings)


def test_empty_admin_list_fails_closed() -> None:
    settings = _settings("")

    assert not is_admin(1001, settings)


def test_malformed_admin_list_fails_closed() -> None:
    settings = _settings("1001,not-a-number")

    assert not is_admin(1001, settings)


def test_every_admin_button_uses_admin_callback_namespace() -> None:
    keyboard = admin_main_keyboard()

    callbacks = [
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data is not None
    ]
    assert callbacks
    assert all(value.startswith("admin:") for value in callbacks)


def test_admin_pages_never_render_api_secret() -> None:
    settings = _settings()

    home = admin_home_text(settings)
    ai_page, _ = admin_page("ai", settings)

    assert settings.openai_api_key not in home
    assert settings.openai_api_key not in ai_page
    assert settings.telegram_bot_token not in home
    assert settings.telegram_bot_token not in ai_page
