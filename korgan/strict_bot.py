from __future__ import annotations

import asyncio
import contextlib
import logging

from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import MenuButtonDefault

from korgan import bot as base_bot
from korgan.admin import router as admin_router
from korgan.client_safe_ui import ClientSafeBot, install_client_safe_runtime
from korgan.config import get_settings
from korgan.contact_handlers import router as contact_router
from korgan.legal.corpus_refresh import start_corpus_refresh_task
from korgan.legal_safety import ConsentMiddleware, router as safety_router
from korgan.menu_start import router as start_router
from korgan.reply_menu_handlers import router as reply_menu_router
from korgan.response_legal import ProductionOpenAILegalService
from korgan.response_menu_handlers import router as response_router
from korgan.ui import main_menu

LOGGER = logging.getLogger(__name__)


async def configure_telegram_menu(bot: ClientSafeBot) -> None:
    # KORGAN already has its own persistent reply keyboard. Keeping Telegram's
    # command list creates a second blue «Меню» button next to the input field,
    # so clear bot commands and restore the default menu-button state.
    await bot.delete_my_commands()
    await bot.set_chat_menu_button(menu_button=MenuButtonDefault())


async def main() -> None:
    settings = get_settings()
    base_bot.service = ProductionOpenAILegalService(settings)
    base_bot.MENU = main_menu()
    install_client_safe_runtime()

    bot = ClientSafeBot(token=settings.telegram_bot_token)
    await configure_telegram_menu(bot)

    dp = Dispatcher(storage=MemoryStorage())
    dp.message.outer_middleware(ConsentMiddleware())

    # Admin must be registered before generic user routers. Every admin handler
    # independently re-checks ADMIN_TELEGRAM_IDS and fails closed.
    dp.include_router(admin_router)
    dp.include_router(start_router)
    dp.include_router(safety_router)
    dp.include_router(contact_router)
    dp.include_router(response_router)
    dp.include_router(reply_menu_router)
    dp.include_router(base_bot.router)

    corpus_task = start_corpus_refresh_task()
    LOGGER.info("Starting KORGAN: client-safe legal UI + verified corpus + claims + responses + contracts")
    try:
        await dp.start_polling(bot)
    finally:
        if corpus_task is not None:
            corpus_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await corpus_task
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
