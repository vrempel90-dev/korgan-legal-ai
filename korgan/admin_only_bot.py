from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import CommandStart
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, MenuButtonCommands, Message

from korgan.admin import admin_home_text, admin_main_keyboard, is_admin, router as admin_router
from korgan.admin_payment_callbacks import router as payment_router
from korgan.admin_payment_store import close_admin_payment_store, init_admin_payment_store
from korgan.config import get_settings

LOGGER = logging.getLogger(__name__)
entry_router = Router(name="admin_only_entry")


@entry_router.message(CommandStart())
async def admin_start(message: Message) -> None:
    user_id = message.from_user.id if message.from_user else None
    settings = get_settings()
    # Customer Telegram AI is intentionally disabled. Non-admin /start is
    # silent so this process exposes no customer-facing bot flow.
    if not is_admin(user_id, settings):
        LOGGER.info("ADMIN_ONLY_START_IGNORED telegram_user_id=%s", user_id)
        return
    await message.answer(admin_home_text(settings), reply_markup=admin_main_keyboard())


async def configure_admin_menu(bot: Bot) -> None:
    await bot.delete_my_commands()
    await bot.set_my_commands([BotCommand(command="admin", description="Админ-панель KORGAN")])
    # Never expose the MiniApp as the Telegram menu button for this admin-only
    # process. MiniApp remains a separate client product.
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())


async def main() -> None:
    settings = get_settings()
    await init_admin_payment_store(settings)

    bot = Bot(token=settings.telegram_bot_token)
    await configure_admin_menu(bot)

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(entry_router)
    dp.include_router(payment_router)
    dp.include_router(admin_router)

    LOGGER.info(
        "Starting KORGAN Telegram admin-only runtime; customer AI routes disabled; admin_count=%s",
        len(settings.admin_ids),
    )
    try:
        await dp.start_polling(bot)
    finally:
        await close_admin_payment_store()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
