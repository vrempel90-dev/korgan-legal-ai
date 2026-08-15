from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from korgan import bot as base_bot
from korgan.config import get_settings
from korgan.menu_handlers import router as menu_router
from korgan.menu_start import router as start_router
from korgan.ui import main_menu
from korgan.verified_openai import VerifiedOpenAILegalService

LOGGER = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()
    base_bot.service = VerifiedOpenAILegalService(settings)
    # Existing response paths keep working, but now use the polished inline menu.
    base_bot.MENU = main_menu()

    bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher(storage=MemoryStorage())
    # UI routers go first so /start and inline callbacks use the new interface.
    dp.include_router(start_router)
    dp.include_router(menu_router)
    dp.include_router(base_bot.router)

    LOGGER.info("Starting KORGAN verified polling with polished inline menu")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
