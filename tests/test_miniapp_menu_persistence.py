from __future__ import annotations

import asyncio

from aiogram import Bot
from aiogram.types import MenuButtonDefault, MenuButtonWebApp

from korgan.localized_transport import LocalizedClientSafeBot


def test_default_startup_menu_becomes_configured_miniapp(monkeypatch) -> None:
    monkeypatch.setenv("MINIAPP_PUBLIC_URL", "https://korgan-miniapp.example/")
    monkeypatch.setenv("TELEGRAM_MINIAPP_MENU_TEXT", "Открыть KORGAN")
    captured: dict[str, object] = {}

    async def fake_set_chat_menu_button(self, **kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(Bot, "set_chat_menu_button", fake_set_chat_menu_button)

    asyncio.run(
        LocalizedClientSafeBot.set_chat_menu_button(
            object(),
            menu_button=MenuButtonDefault(),
        )
    )

    menu = captured["menu_button"]
    assert isinstance(menu, MenuButtonWebApp)
    assert menu.text == "Открыть KORGAN"
    assert menu.web_app.url == "https://korgan-miniapp.example/"


def test_default_menu_remains_default_without_valid_miniapp_url(monkeypatch) -> None:
    monkeypatch.delenv("MINIAPP_PUBLIC_URL", raising=False)
    monkeypatch.delenv("TELEGRAM_MINIAPP_MENU_TEXT", raising=False)
    captured: dict[str, object] = {}

    async def fake_set_chat_menu_button(self, **kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(Bot, "set_chat_menu_button", fake_set_chat_menu_button)

    asyncio.run(
        LocalizedClientSafeBot.set_chat_menu_button(
            object(),
            menu_button=MenuButtonDefault(),
        )
    )

    assert isinstance(captured["menu_button"], MenuButtonDefault)
