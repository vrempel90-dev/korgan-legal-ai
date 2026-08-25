"""Apply production-invariant v2 release semantics to universal Word routes.

Contract and response-to-claim used to have their own release branches.  This
adapter makes them consume the same blocker classification and disclosure
policy as claim/pretrial: only missing user facts may block, while internal
quality residue is delivered with an explicit [СВЕРИТЬ: ...] marker.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiogram.types import BufferedInputFile, Message

from korgan.legal_types import VerificationStatus
from korgan.production_invariants_v2 import (
    _internal_message,
    _mark_delivery_once,
    _user_data_message,
    append_review_markers,
    classify_issue,
    classify_issues,
)
from korgan.telegram_text import fit_caption

LOGGER = logging.getLogger(__name__)


def install_universal_document_invariants_v2() -> None:
    from korgan import bot as base_bot
    from korgan import universal_document_runtime as runtime
    from korgan.contract_docx import build_contract_docx
    from korgan.document_quality import assess_document_quality, rendered_docx_blockers
    from korgan.response_docx import build_response_to_claim_docx
    from korgan.ui import main_menu

    if getattr(runtime, "_korgan_document_invariants_v2", False):
        return

    async def send_contract(message: Message, state: Any) -> None:
        await runtime._save_user_text(message, state, min_length=24)
        context = await base_bot._case_context(state)
        if not context.strip() or len(context.strip()) < 80:
            await runtime._ask_contract(message, state)
            return

        service = base_bot.service
        research_method = getattr(service, "research_contract", None) if service is not None else None
        draft_method = getattr(service, "draft_contract", None) if service is not None else None
        if research_method is None or draft_method is None:
            await message.answer("Функция договоров не загружена в текущую версию сервиса.", reply_markup=main_menu())
            return

        await state.update_data(mode="main")
        lang = str((await state.get_data()).get("language", "ru"))
        menu = main_menu(lang)
        await message.answer("Формирую и проверяю договор…", reply_markup=menu)
        await message.bot.send_chat_action(message.chat.id, "typing")

        try:
            research = await research_method(context, language=lang)
            draft = await draft_method(context, research, language=lang)
            quality = assess_document_quality("contract", context, research, draft)
            issues = quality.repair_issues()
            user_issues, internal_issues = classify_issues(issues)
            if user_issues:
                LOGGER.warning(
                    "UNIVERSAL_WORD_QUALITY kind=contract issues_after=%d blocker_class=NEEDS_USER_DATA",
                    len(issues),
                )
                await message.answer(_user_data_message("договор", user_issues), reply_markup=menu)
                return

            draft.status = VerificationStatus.VERIFIED if quality.ready and not internal_issues else VerificationStatus.NEEDS_VERIFICATION
            file_bytes = build_contract_docx(draft)
            export = rendered_docx_blockers(file_bytes, ready_expected=quality.ready and not internal_issues)
            if export:
                internal_issues.extend(classify_issue(f"экспорт Word: {item}") for item in export)
            if internal_issues:
                file_bytes = append_review_markers(file_bytes, [item.text for item in internal_issues], language=lang)

            LOGGER.info(
                "UNIVERSAL_WORD_QUALITY kind=contract issues_after=%d delivered=1 internal_markers=%d",
                len(issues) + len(export),
                len(internal_issues),
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Universal contract generation failed")
            await message.answer("Не удалось безопасно сформировать договор.", reply_markup=menu)
            return

        if not _mark_delivery_once("contract"):
            return
        if internal_issues:
            caption = (
                f"⚠️ KORGAN QUALITY {quality.score:.1f}/10 · ДОГОВОР С ОТМЕТКАМИ [СВЕРИТЬ]\n"
                "Что осталось проверить:\n" + _internal_message(internal_issues)
            )
        else:
            caption = f"✅ KORGAN QUALITY {quality.score:.1f}/10\nДоговор сформирован в Word (.docx)."
        await message.answer_document(
            BufferedInputFile(file_bytes, filename="KORGAN_dogovor.docx"),
            caption=fit_caption(caption),
            reply_markup=menu,
        )

    async def send_response(message: Message, state: Any) -> None:
        await runtime._save_user_text(message, state)
        context = await base_bot._case_context(state)
        if not runtime._looks_like_claim_materials(context):
            await runtime._ask_response(message, state)
            return

        service = base_bot.service
        research_method = getattr(service, "research_response_to_claim", None) if service is not None else None
        draft_method = getattr(service, "draft_response_to_claim", None) if service is not None else None
        if research_method is None or draft_method is None:
            await message.answer("Функция отзыва на иск не загружена в текущую версию сервиса.", reply_markup=main_menu())
            return

        await state.update_data(mode="main")
        lang = str((await state.get_data()).get("language", "ru"))
        menu = main_menu(lang)
        await message.answer("Формирую и проверяю отзыв на иск…", reply_markup=menu)
        await message.bot.send_chat_action(message.chat.id, "typing")

        try:
            research = await research_method(context, language=lang)
            draft = await draft_method(context, research, language=lang)
            quality = assess_document_quality("response_to_claim", context, research, draft)
            issues = quality.repair_issues()
            user_issues, internal_issues = classify_issues(issues)
            if user_issues:
                LOGGER.warning(
                    "UNIVERSAL_WORD_QUALITY kind=response_to_claim issues_after=%d blocker_class=NEEDS_USER_DATA",
                    len(issues),
                )
                await message.answer(_user_data_message("отзыв на иск", user_issues), reply_markup=menu)
                return

            draft.status = VerificationStatus.VERIFIED if quality.ready and not internal_issues else VerificationStatus.NEEDS_VERIFICATION
            file_bytes = build_response_to_claim_docx(draft)
            export = rendered_docx_blockers(file_bytes, ready_expected=quality.ready and not internal_issues)
            if export:
                internal_issues.extend(classify_issue(f"экспорт Word: {item}") for item in export)
            if internal_issues:
                file_bytes = append_review_markers(file_bytes, [item.text for item in internal_issues], language=lang)

            LOGGER.info(
                "UNIVERSAL_WORD_QUALITY kind=response_to_claim issues_after=%d delivered=1 internal_markers=%d",
                len(issues) + len(export),
                len(internal_issues),
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Universal response-to-claim generation failed")
            await message.answer("Не удалось безопасно сформировать отзыв на иск.", reply_markup=menu)
            return

        if not _mark_delivery_once("response_to_claim"):
            return
        if internal_issues:
            caption = (
                f"⚠️ KORGAN QUALITY {quality.score:.1f}/10 · ОТЗЫВ С ОТМЕТКАМИ [СВЕРИТЬ]\n"
                "Что осталось проверить:\n" + _internal_message(internal_issues)
            )
        else:
            caption = f"✅ KORGAN QUALITY {quality.score:.1f}/10\nОтзыв на иск сформирован в Word (.docx)."
        await message.answer_document(
            BufferedInputFile(file_bytes, filename="KORGAN_otzyv_na_isk.docx"),
            caption=fit_caption(caption),
            reply_markup=menu,
        )

    runtime._send_contract = send_contract
    runtime._send_response = send_response
    runtime._korgan_document_invariants_v2 = True
    LOGGER.info("Installed universal document invariants v2 for contract/response")
