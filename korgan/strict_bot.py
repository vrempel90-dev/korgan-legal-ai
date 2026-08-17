from __future__ import annotations

import asyncio
import contextlib
import logging

from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import MenuButtonDefault

from korgan import bot as base_bot
from korgan.admin import router as admin_router
from korgan.claim_quality_hotfix import install_runtime_hotfix
from korgan.client_safe_ui import ClientSafeBot, install_client_safe_runtime
from korgan.config import get_settings
from korgan.contact_handlers import router as contact_router
from korgan.finalized_litigation import FinalizedProductionClaimService
from korgan.legal.corpus_refresh import start_corpus_refresh_task
from korgan.legal_safety import ConsentMiddleware, router as safety_router
from korgan.menu_start import router as start_router
from korgan.professional_rag_bridge import install_professional_rag_bridge
from korgan.reply_menu_handlers import router as reply_menu_router
from korgan.ui import main_menu

# Install the already proven filing-vs-substance quality policy before the
# universal routers bind their quality functions. Then enrich its single
# professional research pass with local-corpus candidates and keep all
# verification internals out of the client transport.
install_runtime_hotfix()
install_professional_rag_bridge()
install_client_safe_runtime()

from korgan.universal_claim_runtime import router as universal_claim_router  # noqa: E402
from korgan.universal_document_runtime import router as universal_document_router  # noqa: E402

LOGGER = logging.getLogger(__name__)


async def configure_telegram_menu(bot: ClientSafeBot) -> None:
    await bot.delete_my_commands()
    await bot.set_chat_menu_button(menu_button=MenuButtonDefault())


async def main() -> None:
    settings = get_settings()
    base_bot.service = FinalizedProductionClaimService(settings)
    base_bot.MENU = main_menu()

    bot = ClientSafeBot(token=settings.telegram_bot_token)
    await configure_telegram_menu(bot)

    dp = Dispatcher(storage=MemoryStorage())
    dp.message.outer_middleware(ConsentMiddleware())

    dp.include_router(admin_router)
    dp.include_router(start_router)
    dp.include_router(safety_router)
    dp.include_router(contact_router)
    dp.include_router(universal_claim_router)
    dp.include_router(universal_document_router)
    dp.include_router(reply_menu_router)
    dp.include_router(base_bot.router)

    corpus_task = start_corpus_refresh_task()
    LOGGER.info(
        "Starting KORGAN: restored >=8.5 quality core + professional RAG hints + client-safe UI"
    )
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
