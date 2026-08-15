from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from korgan import bot as base_bot
from korgan.config import get_settings
from korgan.strict_openai import StrictOpenAILegalService

LOGGER = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()
    base_bot.service = StrictOpenAILegalService(settings)

    bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(base_bot.router)

    LOGGER.info("Starting KORGAN strict polling (OpenAI + mandatory official research)")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
