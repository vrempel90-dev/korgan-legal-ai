from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import MenuButtonDefault

from korgan import bot as base_bot
from korgan.admin import router as admin_router
from korgan.config import get_settings
from korgan.contact_handlers import router as contact_router
from korgan.legal_safety import ConsentMiddleware, router as safety_router
from korgan.litigation_production import LitigationProductionService
from korgan.menu_start import router as start_router
from korgan.reply_menu_handlers import router as reply_menu_router
from korgan.ui import main_menu
from korgan.universal_claim_runtime import router as universal_claim_router
from korgan.universal_document_runtime import router as universal_document_router

LOGGER = logging.getLogger(__name__)


async def configure_telegram_menu(bot: Bot) -> None:
    # KORGAN already has its own persistent reply keyboard. Keeping Telegram's
    # command list creates a second blue «Меню» button next to the input field,
    # so clear bot commands and restore the default menu-button state.
    await bot.delete_my_commands()
    await bot.set_chat_menu_button(menu_button=MenuButtonDefault())


async def main() -> None:
    settings = get_settings()
    # Telegram/UI stays unchanged. Only the internal legal reasoning core is
    # upgraded: primary research -> adversarial senior research -> professional
    # strategy -> draft -> independent pre-filing review -> repair/release gate.
    base_bot.service = LitigationProductionService(settings)
    base_bot.MENU = main_menu()

    bot = Bot(token=settings.telegram_bot_token)
    await configure_telegram_menu(bot)

    dp = Dispatcher(storage=MemoryStorage())
    dp.message.outer_middleware(ConsentMiddleware())

    # Admin must be registered before generic user routers. Every admin handler
    # independently re-checks ADMIN_TELEGRAM_IDS and fails closed.
    dp.include_router(admin_router)
    dp.include_router(start_router)
    dp.include_router(safety_router)
    dp.include_router(contact_router)

    # Existing user-facing routes and menu are intentionally unchanged.
    dp.include_router(universal_claim_router)
    dp.include_router(universal_document_router)
    dp.include_router(reply_menu_router)
    dp.include_router(base_bot.router)

    LOGGER.info(
        "Starting KORGAN: senior litigation RK core + unchanged Telegram UI + adversarial pre-filing review"
    )
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
