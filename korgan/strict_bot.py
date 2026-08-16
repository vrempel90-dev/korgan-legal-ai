from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, MenuButtonCommands

from korgan import bot as base_bot
from korgan.config import get_settings
from korgan.contact_handlers import router as contact_router
from korgan.legal_safety import ConsentMiddleware, router as safety_router
from korgan.menu_start import router as start_router
from korgan.reply_menu_handlers import router as reply_menu_router
from korgan.response_legal import ProductionOpenAILegalService
from korgan.response_menu_handlers import router as response_router
from korgan.ui import main_menu

LOGGER = logging.getLogger(__name__)


async def configure_telegram_menu(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Открыть KORGAN"),
            BotCommand(command="menu", description="Главное меню"),
            BotCommand(command="terms", description="Условия использования"),
            BotCommand(command="privacy", description="Конфиденциальность"),
            BotCommand(command="help", description="Помощь"),
            BotCommand(command="clear", description="Очистить текущее дело"),
        ]
    )
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())


async def main() -> None:
    settings = get_settings()
    base_bot.service = ProductionOpenAILegalService(settings)
    base_bot.MENU = main_menu()

    bot = Bot(token=settings.telegram_bot_token)
    await configure_telegram_menu(bot)

    dp = Dispatcher(storage=MemoryStorage())
    dp.message.outer_middleware(ConsentMiddleware())

    dp.include_router(start_router)
    dp.include_router(safety_router)
    dp.include_router(contact_router)
    dp.include_router(response_router)
    dp.include_router(reply_menu_router)
    dp.include_router(base_bot.router)

    LOGGER.info("Starting KORGAN: Article 353 + claims + responses to claims + truncation-safe contracts + WhatsApp contacts")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
