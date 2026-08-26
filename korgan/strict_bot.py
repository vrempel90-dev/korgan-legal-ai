from __future__ import annotations

import asyncio
import contextlib
import logging

from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import MenuButtonDefault

from korgan import bot as base_bot
from korgan.admin import router as admin_router
from korgan.claim_pipeline_v2 import ClaimPipelineV2Adapter, claim_pipeline_v2_mode
from korgan.claim_quality_hotfix import install_runtime_hotfix
from korgan.claim_service_mux import ClaimServiceMux
from korgan.client_document_guidance_router import router as client_document_guidance_router
from korgan.client_document_runtime_guidance import install_client_document_runtime_guidance
from korgan.client_safe_ui import install_client_safe_runtime
from korgan.config import get_settings
from korgan.consultation_quota import close_consultation_store, init_consultation_store
from korgan.consultation_quota_bridge import install_consultation_quota_bridge
from korgan.consultation_quota_runtime import router as consultation_quota_router
from korgan.consultation_ui_runtime import router as consultation_ui_router
from korgan.contact_handlers import router as contact_router
from korgan.document_category_router import router as document_category_router
from korgan.document_generator_ownership_guard import install_document_generator_ownership_guard
from korgan.document_menu_entry import router as document_menu_entry_router
from korgan.document_section_lock import router as document_section_lock_router
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
from korgan.prepayment_gate import install_generation_prepayment_gate
from korgan.prepayment_runtime import router as prepayment_router
from korgan.pretrial_response import PretrialResponseProductionService
from korgan.pretrial_response_runtime import install_pretrial_response_transport, router as pretrial_response_router
from korgan.pretrial_runtime import router as pretrial_router
from korgan.professional_consultation_guard import install_professional_consultation_guard
from korgan.professional_rag_bridge import install_professional_rag_bridge
from korgan.reply_menu_handlers import router as reply_menu_router
from korgan.request_race_guard import install_request_race_guard
from korgan.response_voice_guard import install_response_voice_guard
from korgan.review_cta_runtime import router as review_cta_router
from korgan.stable_legal_release import install_stable_legal_release
from korgan.token_budget_guard import apply_token_budget_guard
from korgan.ui import main_menu
from korgan.universal_word_final_hardening import install_universal_word_final_hardening
from korgan.universal_word_quality_guard import install_universal_word_quality_guard
from korgan.upload_followup_guard import install_upload_followup_guard

install_runtime_hotfix()
install_kazakh_legal_bridge()
install_kazakh_article_forms()
install_professional_rag_bridge()
install_stable_legal_release()
# Ordinary consultations use the same source-bound standard as documents: an
# exact article/rate/deadline cannot reach Telegram unless the current response
# actually opened an allowed official source and the rule passed verification.
install_professional_consultation_guard()
# One bounded repair policy for all five Word document types. It raises the
# filing-ready target to 10/10 while preserving the existing quality fallback;
# payment gating remains independent and prevents unpaid delivery/generation.
install_universal_word_quality_guard()
# Exact Decimal arithmetic and source-safe monetary extraction are layered after
# the universal guard so its release path cannot select principal debt as a
# penalty or lose precision on large KZT amounts.
install_universal_word_final_hardening()
install_client_safe_runtime()
install_pretrial_response_transport()
install_response_voice_guard()
install_payment_pdf_hotfix()
# Keep the transport-level gate as a fail-closed fallback. Normal requests are
# paid before generation; only a verified paid-generation context can pass it.
# Any unexpected generator still gets held, never exposed for free.
install_payment_gate()
install_payment_delivery_bridge()
install_upload_followup_guard()
install_request_race_guard()
install_consultation_quota_bridge()

from korgan.universal_claim_runtime import router as universal_claim_router  # noqa: E402
from korgan.universal_document_runtime import router as universal_document_router  # noqa: E402

# The selected button must remain authoritative all the way down to the actual
# research/drafting function. Install this after every document runtime exists,
# but before the prepayment wrapper is layered on top of the generators.
install_document_generator_ownership_guard()

# Install only after all active generator modules are loaded. Every normal path
# that can enter legal research/drafting is wrapped by the same prepayment rule;
# menu/intake prompts remain free and do not generate a Word document.
install_generation_prepayment_gate()
# Client guidance is presentation-only and must be layered after the canonical
# generator/prepayment wiring. It wraps intake prompts, never generators.
install_client_document_runtime_guidance()

LOGGER = logging.getLogger(__name__)


async def configure_telegram_menu(bot: LocalizedClientSafeBot) -> None:
    await bot.delete_my_commands()
    await bot.set_chat_menu_button(menu_button=MenuButtonDefault())


async def main() -> None:
    settings = get_settings()
    apply_token_budget_guard(settings)
    stable_service = PretrialResponseProductionService(settings)
    base_bot.service = ClaimPipelineV2Adapter(ClaimServiceMux(stable_service, settings))
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
    # Persistent navigation must win over every active document/payment/intake
    # state. Otherwise the first tap on «Документ / Құжат» can be swallowed as
    # case text and the client has to tap twice.
    dp.include_router(document_menu_entry_router)
    # Keep prepayment compatibility callbacks before the generic payment router.
    # New negative-id payments do not require an admin decision: the receipt
    # handler invokes paid generation immediately after strict AI verification.
    dp.include_router(prepayment_router)
    dp.include_router(payment_router)
    dp.include_router(contact_router)
    # Exact RU/KK consultation and price buttons are handled here before the
    # legacy language/menu routers, so client-facing tariff text stays in sync.
    dp.include_router(consultation_ui_router)
    # These three KK document callbacks must enter the same immutable request
    # scope as RU and the other document kinds before the legacy Kazakh router.
    dp.include_router(client_document_guidance_router)
    dp.include_router(kazakh_router)
    dp.include_router(review_cta_router)
    # The selected document button owns all intake text. This router must run
    # before text-based intent/category routers so case facts cannot switch a
    # claim into a contract, pretrial demand or response (and vice versa).
    dp.include_router(document_section_lock_router)
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
        "Starting KORGAN: hard document-generator ownership + payment-before-generation + fail-closed payment fallback + strict document section lock + 10/10 quality target + exact Decimal filing arithmetic + source-bound consultations + preliminary Word fallback + RAG + RU/KK + claims/pretrial/pretrial-response + stable citation release + strict receipt AI verification + automatic paid generation=%s + manual payment confirmation=False + consultation limit=%s + claim pipeline v2=%s",
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
