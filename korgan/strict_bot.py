from __future__ import annotations

import asyncio
import contextlib
import logging

from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import MenuButtonDefault

from korgan import bot as base_bot
from korgan.additive_legal_guard import AdditiveLegalGuardService, install_global_current_law_guard
from korgan.admin import router as admin_router
from korgan.claim_quality_hotfix import install_runtime_hotfix
from korgan.claim_route_lock import router as claim_route_lock_router
from korgan.client_safe_ui import install_client_safe_runtime
from korgan.config import get_settings
from korgan.contact_handlers import router as contact_router
from korgan.document_intent_guard import router as intent_guard_router
from korgan.kazakh_article_forms import install_kazakh_article_forms
from korgan.kazakh_legal_bridge import install_kazakh_legal_bridge
from korgan.kazakh_ui import router as kazakh_router
from korgan.language_context import LanguageContextMiddleware
from korgan.legal.citation_extensions import install_extended_citation_audit
from korgan.legal.corpus import DEFAULT_DB_PATH
from korgan.legal.corpus_refresh import autoload_enabled, refresh_corpus_once, start_corpus_refresh_task
from korgan.legal_safety import ConsentMiddleware, router as safety_router
from korgan.localized_transport import LocalizedClientSafeBot
from korgan.menu_start import router as start_router
from korgan.pretrial_runtime import router as pretrial_router
from korgan.professional_rag_bridge import install_professional_rag_bridge
from korgan.reply_menu_handlers import router as reply_menu_router
from korgan.stable_legal_release import install_stable_legal_release
from korgan.ui import main_menu

install_runtime_hotfix()
install_kazakh_legal_bridge()
install_kazakh_article_forms()
install_professional_rag_bridge()
install_stable_legal_release()
install_extended_citation_audit()
install_client_safe_runtime()
# Current-law/source checks remain global. Material-law completeness is also
# global at the service layer: substantive demands in claims, responses,
# pre-trial demands and contracts may not be justified only by procedural law,
# state duty or representative-cost rules.
install_global_current_law_guard()

from korgan.universal_claim_runtime import router as universal_claim_router  # noqa: E402
from korgan.universal_document_runtime import router as universal_document_router  # noqa: E402

LOGGER = logging.getLogger(__name__)


async def configure_telegram_menu(bot: LocalizedClientSafeBot) -> None:
    await bot.delete_my_commands()
    await bot.set_chat_menu_button(menu_button=MenuButtonDefault())


async def ensure_startup_corpus_ready() -> None:
    """Do not accept legal-document requests before the verified core corpus exists.

    Railway containers use ephemeral application storage. After a fresh deploy
    the SQLite corpus can therefore be absent for the first minute or two. The
    source-verification pipeline would otherwise begin work before its local
    legal corpus is ready. When autoload is enabled and no corpus is present,
    build it synchronously before Telegram polling starts. If a healthy corpus
    already exists, startup remains fast and the normal background refresh keeps
    it current.
    """
    if not autoload_enabled():
        return
    if DEFAULT_DB_PATH.exists() and DEFAULT_DB_PATH.stat().st_size > 0:
        LOGGER.info("KORGAN startup corpus already present path=%s", DEFAULT_DB_PATH)
        return

    LOGGER.info("KORGAN startup waiting for verified Adilet core corpus path=%s", DEFAULT_DB_PATH)
    total = await asyncio.to_thread(refresh_corpus_once, DEFAULT_DB_PATH)
    if total <= 0 or not DEFAULT_DB_PATH.exists():
        raise RuntimeError("KORGAN startup corpus refresh produced no verified provisions")
    LOGGER.info("KORGAN startup corpus READY provisions=%d path=%s", total, DEFAULT_DB_PATH)


async def main() -> None:
    settings = get_settings()
    # Preserve all deployed generators and add one source-bound completeness
    # layer across every supported generated document type.
    base_bot.service = AdditiveLegalGuardService(settings)
    base_bot.MENU = main_menu()

    # A fresh Railway container must not start accepting document requests while
    # source-bound verification is still missing its local legal corpus.
    await ensure_startup_corpus_ready()

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
    # A claim selected from the document menu is a hard intent lock. This router
    # must run before legacy document-menu callbacks and consultation fallbacks.
    dp.include_router(claim_route_lock_router)
    # Intent lock must run before every document-specific waiting handler and
    # before the Kazakh consultation catch-all.
    dp.include_router(intent_guard_router)
    dp.include_router(pretrial_router)
    dp.include_router(kazakh_router)
    dp.include_router(universal_claim_router)
    dp.include_router(universal_document_router)
    dp.include_router(reply_menu_router)
    dp.include_router(base_bot.router)

    corpus_task = start_corpus_refresh_task()
    LOGGER.info(
        "Starting KORGAN: verified corpus ready + hard claim-to-DOCX routing + universal material-law completeness + current RK Adilet RAG + RU/KK + no questionnaires"
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
