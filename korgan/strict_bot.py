from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, MenuButtonCommands

from korgan.admin import router as admin_router
from korgan.config import get_settings
from korgan.miniapp_document_payments import (
    close_document_payment_store,
    init_document_payment_store,
)

LOGGER = logging.getLogger(__name__)


async def configure_admin_bot(bot: Bot) -> None:
    """Expose only the administrator entry point in Telegram."""
    await bot.delete_my_commands()
    await bot.set_my_commands(
        [BotCommand(command="admin", description="Админ-панель KORGAN")]
    )
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())


async def main() -> None:
    settings = get_settings()
    await init_document_payment_store(settings)

    bot = Bot(token=settings.telegram_bot_token)
    await configure_admin_bot(bot)

    dp = Dispatcher(storage=MemoryStorage())
    # Deliberately include only the admin router. No consultation, document,
    # upload, start/menu, OpenAI or other customer-facing Telegram routes are
    # registered in this process.
    dp.include_router(admin_router)

    LOGGER.info(
        "Starting KORGAN admin-only Telegram polling; user AI routes disabled; admins=%s",
        sorted(settings.admin_ids),
    )
    try:
        await dp.start_polling(bot)
    finally:
        await close_document_payment_store()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
