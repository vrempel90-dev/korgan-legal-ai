from __future__ import annotations

import asyncio
import contextlib
import logging
import os

from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import MenuButtonDefault, MenuButtonWebApp, WebAppInfo

from korgan import bot as base_bot
from korgan.admin import router as admin_router
from korgan.admin_report import start_admin_report_task
from korgan.claim_generation_progress import install_claim_generation_progress
from korgan.claim_pipeline_v2 import ClaimPipelineV2Adapter, claim_pipeline_v2_mode
from korgan.claim_quality_hotfix import install_runtime_hotfix
from korgan.claim_service_mux import ClaimServiceMux
from korgan.client_document_guidance_router import router as client_document_guidance_router
from korgan.client_document_runtime_guidance import install_client_document_runtime_guidance
from korgan.client_safe_ui import install_client_safe_runtime
from korgan.config import get_settings
from korgan.consultation_local_corpus_bridge import install_local_first_consultation
from korgan.consultation_paid_delivery_guard import install_consultation_paid_delivery_guard
from korgan.consultation_quota import close_consultation_store, init_consultation_store
from korgan.consultation_quota_bridge import install_consultation_quota_bridge
from korgan.consultation_quota_runtime import router as consultation_quota_router
from korgan.consultation_ui_runtime import router as consultation_ui_router
from korgan.contact_handlers import router as contact_router
from korgan.document_category_router import router as document_category_router
from korgan.document_generator_ownership_guard import install_document_generator_ownership_guard
from korgan.document_menu_entry import router as document_menu_entry_router
from korgan.document_receipt_replay_guard import (
    close_document_receipt_replay_guard,
    init_document_receipt_replay_guard,
)
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
from korgan.telegram_branding import ensure_telegram_profile_branding
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
install_professional_consultation_guard()
install_local_first_consultation()
install_universal_word_quality_guard()
install_universal_word_final_hardening()
install_client_safe_runtime()
install_pretrial_response_transport()
install_response_voice_guard()
install_payment_pdf_hotfix()
install_payment_gate()
install_payment_delivery_bridge()
install_upload_followup_guard()
install_request_race_guard()
install_consultation_quota_bridge()
install_consultation_paid_delivery_guard()

from korgan.universal_claim_runtime import router as universal_claim_router  # noqa: E402
from korgan.universal_document_runtime import router as universal_document_router  # noqa: E402

install_document_generator_ownership_guard()
install_generation_prepayment_gate()
install_client_document_runtime_guidance()
install_claim_generation_progress()

LOGGER = logging.getLogger(__name__)
_DISABLE_VALUES = {"1", "true", "yes", "on", "disabled"}


def telegram_agent_disabled() -> bool:
    return str(os.getenv("KORGAN_TELEGRAM_AGENT_DISABLED", "") or "").strip().lower() in _DISABLE_VALUES


async def configure_telegram_menu(bot: LocalizedClientSafeBot) -> None:
    await bot.delete_my_commands()
    miniapp_url = str(os.getenv("MINIAPP_PUBLIC_URL", "") or "").strip()
    if miniapp_url:
        menu_text = str(os.getenv("TELEGRAM_MINIAPP_MENU_TEXT", "KORGAN") or "KORGAN").strip() or "KORGAN"
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text=menu_text,
                web_app=WebAppInfo(url=miniapp_url),
            )
        )
        return
    await bot.set_chat_menu_button(menu_button=MenuButtonDefault())


async def main() -> None:
    # Production kill switch is evaluated before reading credentials, touching
    # Telegram, opening DB-backed bot stores or starting background jobs. This
    # keeps the Mini App operational while making the separate polling agent a
    # true no-op. The standard Procfile stays unchanged so accidental entrypoint
    # drift remains covered by the existing production tests.
    if telegram_agent_disabled():
        LOGGER.warning("KORGAN_TELEGRAM_AGENT_DISABLED polling_not_started=true")
        return

    settings = get_settings()
    apply_token_budget_guard(settings)
    stable_service = PretrialResponseProductionService(settings)
    base_bot.service = ClaimPipelineV2Adapter(ClaimServiceMux(stable_service, settings))
    base_bot.MENU = main_menu()
    await init_consultation_store(settings)
    await init_document_receipt_replay_guard(settings)

    bot = LocalizedClientSafeBot(token=settings.telegram_bot_token)
    await configure_telegram_menu(bot)
    if str(getattr(settings, "database_url", "") or "").strip():
        await ensure_telegram_profile_branding(settings)

    dp = Dispatcher(storage=MemoryStorage())
    language_middleware = LanguageContextMiddleware()
    dp.message.outer_middleware(language_middleware)
    dp.callback_query.outer_middleware(language_middleware)
    dp.message.outer_middleware(ConsentMiddleware())

    dp.include_router(admin_router)
    dp.include_router(start_router)
    dp.include_router(safety_router)
    dp.include_router(document_menu_entry_router)
    dp.include_router(prepayment_router)
    dp.include_router(payment_router)
    dp.include_router(contact_router)
    dp.include_router(consultation_ui_router)
    dp.include_router(client_document_guidance_router)
    dp.include_router(kazakh_router)
    dp.include_router(review_cta_router)
    dp.include_router(document_section_lock_router)
    dp.include_router(document_category_router)
    dp.include_router(pretrial_response_router)
    dp.include_router(pretrial_router)
    dp.include_router(universal_claim_router)
    dp.include_router(universal_document_router)
    dp.include_router(reply_menu_router)
    dp.include_router(consultation_quota_router)
    dp.include_router(base_bot.router)

    corpus_task = start_corpus_refresh_task()
    admin_report_task = start_admin_report_task(bot, settings)
    LOGGER.info(
        "Starting KORGAN: local-corpus-first research/consultation + guarded web fallback + claim progress + hard document-generator ownership + payment-before-generation + fail-closed payment fallback + strict document section lock + 10/10 quality target + exact Decimal filing arithmetic + source-bound consultations + preliminary Word fallback + RAG + RU/KK + claims/pretrial/pretrial-response + stable citation release + deterministic Kaspi OFD fiscal receipt verification + durable receipt anti-replay + paid-delivery idempotency + automatic paid generation=%s + manual payment confirmation=False + consultation limit=%s + claim pipeline v2=%s + admin daily report=%s",
        settings.payments_enabled,
        settings.consultation_limit_enabled,
        claim_pipeline_v2_mode(),
        getattr(settings, "admin_report_id", None) is not None,
    )
    try:
        await dp.start_polling(bot)
    finally:
        if admin_report_task is not None:
            admin_report_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await admin_report_task
        if corpus_task is not None:
            corpus_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await corpus_task
        await close_document_receipt_replay_guard()
        await close_consultation_store()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
