from __future__ import annotations

import asyncio
import contextlib
import logging

from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import MenuButtonDefault

from korgan import bot as base_bot
from korgan.admin import router as admin_router
from korgan.auto_payment_runtime import install_auto_payment, router as auto_payment_router
from korgan.claim_pipeline_v2 import ClaimPipelineV2Adapter, claim_pipeline_v2_mode
from korgan.claim_quality_hotfix import install_runtime_hotfix
from korgan.client_safe_ui import install_client_safe_runtime
from korgan.config import get_settings
from korgan.consultation_quota import close_consultation_store, init_consultation_store
from korgan.consultation_quota_bridge import install_consultation_quota_bridge
from korgan.consultation_quota_runtime import router as consultation_quota_router
from korgan.consultation_ui_runtime import router as consultation_ui_router
from korgan.contact_handlers import router as contact_router
from korgan.document_category_router import router as document_category_router
from korgan.kazakh_article_forms import install_kazakh_article_forms
from korgan.kazakh_legal_bridge import install_kazakh_legal_bridge
from korgan.kazakh_ui import router as kazakh_router
from korgan.language_context import LanguageContextMiddleware
from korgan.legal.corpus_refresh import start_corpus_refresh_task
from korgan.legal_safety import ConsentMiddleware, router as safety_router
from korgan.localized_transport import LocalizedClientSafeBot
from korgan.menu_start import router as start_router
from korgan.payment_delivery_bridge import install_payment_delivery_bridge
from korgan.payment_gate import install_payment_gate
from korgan.payment_pdf_hotfix import install_payment_pdf_hotfix
from korgan.payment_runtime import router as payment_router
from korgan.pretrial_response import PretrialResponseProductionService
from korgan.pretrial_response_runtime import install_pretrial_response_transport, router as pretrial_response_router
from korgan.pretrial_runtime import router as pretrial_router
from korgan.professional_rag_bridge import install_professional_rag_bridge
from korgan.reply_menu_handlers import router as reply_menu_router
from korgan.response_voice_guard import install_response_voice_guard
from korgan.review_cta_runtime import router as review_cta_router
from korgan.stable_legal_release import install_stable_legal_release
from korgan.ui import main_menu

install_runtime_hotfix()
install_kazakh_legal_bridge()
install_kazakh_article_forms()
install_professional_rag_bridge()
install_stable_legal_release()
install_client_safe_runtime()
install_pretrial_response_transport()
install_response_voice_guard()
install_auto_payment()
install_payment_pdf_hotfix()
install_payment_gate()
install_payment_delivery_bridge()
install_consultation_quota_bridge()

from korgan.universal_claim_runtime import router as universal_claim_router  # noqa: E402
from korgan.universal_document_runtime import router as universal_document_router  # noqa: E402

LOGGER = logging.getLogger(__name__)


async def configure_telegram_menu(bot: LocalizedClientSafeBot) -> None:
    await bot.delete_my_commands()
    await bot.set_chat_menu_button(menu_button=MenuButtonDefault())


async def main() -> None:
    settings = get_settings()
    stable_service = PretrialResponseProductionService(settings)
    base_bot.service = ClaimPipelineV2Adapter(stable_service)
    base_bot.MENU = main_menu()
    await init_consultation_store(settings)

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
    # Successful receipt images are consumed here first and release the held
    # document immediately. The legacy manual router stays registered below as
    # a compatibility fallback for its non-receipt callbacks/text prompts.
    dp.include_router(auto_payment_router)
    dp.include_router(payment_router)
    dp.include_router(contact_router)
    # Exact RU/KK consultation and price buttons are handled here before the
    # legacy language/menu routers, so client-facing tariff text stays in sync.
    dp.include_router(consultation_ui_router)
    dp.include_router(kazakh_router)
    dp.include_router(review_cta_router)
    dp.include_router(document_category_router)
    dp.include_router(pretrial_response_router)
    dp.include_router(pretrial_router)
    dp.include_router(universal_claim_router)
    dp.include_router(universal_document_router)
    dp.include_router(reply_menu_router)
    # Must remain immediately before base_bot.router: all document/menu routers
    # get first refusal, while ordinary legal questions are quota-gated here.
    # KazakhLegalText yields to this router while the quota feature is enabled.
    dp.include_router(consultation_quota_router)
    dp.include_router(base_bot.router)

    corpus_task = start_corpus_refresh_task()
    LOGGER.info(
        "Starting KORGAN: >=8.5 quality core + RAG + RU/KK + claims/pretrial/pretrial-response + stable citation release + AI receipt release=%s + consultation limit=%s + claim pipeline v2=%s",
        settings.payments_enabled,
        settings.consultation_limit_enabled,
        claim_pipeline_v2_mode(),
    )
    try:
        await dp.start_polling(bot)
    finally:
        if corpus_task is not None:
            corpus_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await corpus_task
        await close_consultation_store()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
