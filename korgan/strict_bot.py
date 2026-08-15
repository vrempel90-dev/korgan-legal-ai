from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from korgan import bot as base_bot
from korgan.config import get_settings
from korgan.verified_openai import VerifiedOpenAILegalService

LOGGER = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()
    base_bot.service = VerifiedOpenAILegalService(settings)

    bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(base_bot.router)

    LOGGER.info("Starting KORGAN verified polling (OpenAI + source-bound current-law research)")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
