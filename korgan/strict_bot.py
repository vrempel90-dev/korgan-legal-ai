from __future__ import annotations

import asyncio
import contextlib
import logging

from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import MenuButtonDefault

from korgan import bot as base_bot
from korgan.admin import router as admin_router
from korgan.client_safe_ui import install_client_safe_runtime
from korgan.config import get_settings
from korgan.contact_handlers import router as contact_router
from korgan.kazakh_citation_compat import install_kazakh_citation_compat
from korgan.language_context import LanguageContextMiddleware
from korgan.legal.corpus_refresh import start_corpus_refresh_task
from korgan.legal_safety import ConsentMiddleware, router as safety_router
from korgan.localized_transport import LocalizedClientSafeBot
from korgan.menu_start import router as start_router
from korgan.pretrial import PretrialProductionService
from korgan.pretrial_runtime import router as pretrial_router
from korgan.reply_menu_handlers import router as reply_menu_router
from korgan.response_menu_handlers import router as response_router
from korgan.ui import main_menu

LOGGER = logging.getLogger(__name__)


async def configure_telegram_menu(bot: LocalizedClientSafeBot) -> None:
    await bot.delete_my_commands()
    await bot.set_chat_menu_button(menu_button=MenuButtonDefault())


async def main() -> None:
    settings = get_settings()
    install_kazakh_citation_compat()
    base_bot.service = PretrialProductionService(settings)
    base_bot.MENU = main_menu()
    install_client_safe_runtime()

    bot = LocalizedClientSafeBot(token=settings.telegram_bot_token)
    await configure_telegram_menu(bot)

    dp = Dispatcher(storage=MemoryStorage())
    language_middleware = LanguageContextMiddleware()
    dp.message.outer_middleware(language_middleware)
    dp.callback_query.outer_middleware(language_middleware)
    dp.message.outer_middleware(ConsentMiddleware())

    dp.include_router(admin_router)
    dp.include_router(start_router)
    dp.include_router(safety_router)
    dp.include_router(contact_router)
    dp.include_router(pretrial_router)
    dp.include_router(response_router)
    dp.include_router(reply_menu_router)
    dp.include_router(base_bot.router)

    corpus_task = start_corpus_refresh_task()
    LOGGER.info("Starting KORGAN: client-safe RU/KK UI + verified corpus + claims + responses + contracts + button-only pretrial")
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
