from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.filters import BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from korgan import bot as base_bot
from korgan.contract_docx import build_contract_docx
from korgan.contract_intent import is_contract_drafting_request
from korgan.document_quality import assess_document_quality, rendered_docx_blockers
from korgan.legal_types import VerificationStatus
from korgan.request_scope import request_label, start_new_document_request
from korgan.response_docx import build_response_to_claim_docx
from korgan.response_intent import is_response_to_claim_request
from korgan.telegram_text import bullets, fit_caption
from korgan.ui import main_menu
from korgan.universal_claim_runtime import begin_claim_request

LOGGER = logging.getLogger(__name__)
router = Router(name="universal-quality-documents")


class ContractDetailsFilter(BaseFilter):
    async def __call__(self, message: Message, state: FSMContext) -> bool:
        data = await state.get_data()
        return data.get("mode") == "contract_details" and bool(message.text) and not message.text.startswith("/")


class ResponseDetailsFilter(BaseFilter):
    async def __call__(self, message: Message, state: FSMContext) -> bool:
        data = await state.get_data()
        return data.get("mode") == "response_details" and bool(message.text) and not message.text.startswith("/")


class ContractRequestFilter(BaseFilter):
    async def __call__(self, message: Message, state: FSMContext) -> bool:
        data = await state.get_data()
        if data.get("mode") in {"consultation", "response_details"}:
            return False
        if is_response_to_claim_request(message.text):
            return False
        return is_contract_drafting_request(message.text)


class ResponseRequestFilter(BaseFilter):
    async def __call__(self, message: Message, state: FSMContext) -> bool:
        data = await state.get_data()
        if data.get("mode") in {"consultation", "contract_details"}:
            return False
        return is_response_to_claim_request(message.text)


async def _save_user_text(message: Message, state: FSMContext, *, min_length: int = 1) -> None:
    if message.from_user is not None and message.from_user.is_bot:
        return
    text = (message.text or "").strip()
    if not text or len(text) < min_length:
        return
    if text in {"📄 Документ", "🤝 Договор", "🛡 Отзыв на иск", "⚖️ Исковое заявление"}:
        return
    data = await state.get_data()
    facts = list(data.get("facts", []) or [])
    if text not in facts[-3:]:
        facts.append(text)
    await state.update_data(facts=facts[-20:])


def _looks_like_claim_materials(context: str) -> bool:
    text = " ".join((context or "").split()).lower()
    if not text:
        return False
    if re.search(r"\bисков\w*\s+заявлен\w*\b", text):
        return True
    return bool(
        re.search(r"\bистец\w*\b", text)
        and re.search(r"\bответчик\w*\b", text)
        and re.search(r"\bтребован\w*\b|\bпросит\w*\b|\bвзыскат\w*\b", text)
    )


async def _ask_contract(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    lang = str(data.get("language", "ru"))
    await state.update_data(mode="contract_details")
    await message.answer(
        f"🆕 Новая заявка — {request_label('contract', lang)}.\n\n"
        "Опишите договор одним сообщением: вид/цель договора, стороны и роли, предмет, цена/оплата, срок и важные условия. "
        "Можно также приложить материалы. После этого KORGAN проверит право РК и подготовит Word.",
        reply_markup=main_menu(lang),
    )


async def _ask_response(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    lang = str(data.get("language", "ru"))
    await state.update_data(mode="response_details")
    await message.answer(
        f"🆕 Новая заявка — {request_label('response', lang)}.\n\n"
        "Пришлите иск (PDF/DOCX/фото) или вставьте его требования текстом. Если можете, одним сообщением добавьте позицию ответчика, "
        "оспариваемые факты, доказательства, суд и номер дела. После этого KORGAN подготовит отзыв в Word.",
        reply_markup=main_menu(lang),
    )


async def _send_contract(message: Message, state: FSMContext) -> None:
    await _save_user_text(message, state, min_length=24)
    context = await base_bot._case_context(state)
    if not context.strip() or len(context.strip()) < 80:
        await _ask_contract(message, state)
        return

    service = base_bot.service
    research_method = getattr(service, "research_contract", None) if service is not None else None
    draft_method = getattr(service, "draft_contract", None) if service is not None else None
    if research_method is None or draft_method is None:
        await message.answer("Функция договоров не загружена в текущую версию сервиса.", reply_markup=main_menu())
        return

    await state.update_data(mode="main")
    lang = str((await state.get_data()).get("language", "ru"))
    await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        research = await research_method(context, language=lang)
        draft = await draft_method(context, research, language=lang)
        quality = assess_document_quality("contract", context, research, draft)
        draft.status = VerificationStatus.VERIFIED if quality.ready else VerificationStatus.NEEDS_VERIFICATION
        file_bytes = build_contract_docx(draft)
    except Exception:
        LOGGER.exception("Universal contract generation failed")
        await message.answer(
            "Не удалось безопасно сформировать договор. KORGAN не будет выдавать неподтверждённый текст как готовый документ.",
            reply_markup=main_menu(),
        )
        return

    export_blockers = rendered_docx_blockers(file_bytes, ready_expected=quality.ready)
    if quality.ready and export_blockers:
        LOGGER.error("UNIVERSAL_CONTRACT_DOCX_BLOCK quality=%.1f issues=%s", quality.score, export_blockers)
        await message.answer("Готовый Word не выпущен: экспорт не прошёл финальную проверку качества.", reply_markup=main_menu())
        return

    if quality.ready:
        caption = f"✅ KORGAN QUALITY {quality.score:.1f}/10\nДоговор сформирован в Word (.docx)."
    else:
        caption = f"⚠️ PRELIMINARY · KORGAN QUALITY {quality.score:.1f}/10\nПроект договора сформирован, но не достиг порога 8.5/10."
        checks = quality.repair_issues()[:6]
        if checks:
            caption += "\n\nПеред подписанием требуется:\n" + bullets(checks)

    await message.answer_document(
        BufferedInputFile(file_bytes, filename="KORGAN_dogovor.docx"),
        caption=fit_caption(caption),
        reply_markup=main_menu(),
    )


async def _send_response(message: Message, state: FSMContext) -> None:
    await _save_user_text(message, state)
    context = await base_bot._case_context(state)
    if not _looks_like_claim_materials(context):
        await _ask_response(message, state)
        return

    service = base_bot.service
    research_method = getattr(service, "research_response_to_claim", None) if service is not None else None
    draft_method = getattr(service, "draft_response_to_claim", None) if service is not None else None
    if research_method is None or draft_method is None:
        await message.answer("Функция отзыва на иск не загружена в текущую версию сервиса.", reply_markup=main_menu())
        return

    await state.update_data(mode="main")
    lang = str((await state.get_data()).get("language", "ru"))
    await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        research = await research_method(context, language=lang)
        draft = await draft_method(context, research, language=lang)
        quality = assess_document_quality("response_to_claim", context, research, draft)
        draft.status = VerificationStatus.VERIFIED if quality.ready else VerificationStatus.NEEDS_VERIFICATION
        file_bytes = build_response_to_claim_docx(draft)
    except Exception:
        LOGGER.exception("Universal response-to-claim generation failed")
        await message.answer(
            "Не удалось безопасно сформировать отзыв. KORGAN не будет выдавать неподтверждённый текст как готовый документ.",
            reply_markup=main_menu(),
        )
        return

    export_blockers = rendered_docx_blockers(file_bytes, ready_expected=quality.ready)
    if quality.ready and export_blockers:
        LOGGER.error("UNIVERSAL_RESPONSE_DOCX_BLOCK quality=%.1f issues=%s", quality.score, export_blockers)
        await message.answer("Готовый Word не выпущен: экспорт не прошёл финальную проверку качества.", reply_markup=main_menu())
        return

    if quality.ready:
        caption = f"✅ KORGAN QUALITY {quality.score:.1f}/10\nОтзыв на иск сформирован в Word (.docx)."
    else:
        caption = f"⚠️ PRELIMINARY · KORGAN QUALITY {quality.score:.1f}/10\nПроект отзыва сформирован, но не достиг порога 8.5/10."
        checks = quality.repair_issues()[:6]
        if checks:
            caption += "\n\nПеред подачей требуется:\n" + bullets(checks)

    await message.answer_document(
        BufferedInputFile(file_bytes, filename="KORGAN_otzyv_na_isk.docx"),
        caption=fit_caption(caption),
        reply_markup=main_menu(),
    )


@router.message(ContractDetailsFilter())
async def contract_details(message: Message, state: FSMContext) -> None:
    await _save_user_text(message, state)
    await state.update_data(mode="main")
    await _send_contract(message, state)


@router.message(ResponseDetailsFilter())
async def response_details(message: Message, state: FSMContext) -> None:
    await _save_user_text(message, state)
    await state.update_data(mode="main")
    await _send_response(message, state)


@router.message(ResponseRequestFilter())
async def response_request(message: Message, state: FSMContext) -> None:
    await start_new_document_request(state, kind="response", mode="main")
    await _send_response(message, state)


@router.message(ContractRequestFilter())
async def contract_request(message: Message, state: FSMContext) -> None:
    await start_new_document_request(state, kind="contract", mode="main")
    await _send_contract(message, state)


@router.callback_query(F.data == "doc:claim")
async def claim_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is not None:
        await start_new_document_request(state, kind="claim", mode="universal_claim_waiting")
        await begin_claim_request(callback.message, state)


@router.callback_query(F.data == "doc:contract")
async def contract_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is not None:
        await start_new_document_request(state, kind="contract", mode="contract_details")
        await _ask_contract(callback.message, state)


@router.callback_query(F.data == "doc:response")
async def response_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is not None:
        await start_new_document_request(state, kind="response", mode="response_details")
        await _ask_response(callback.message, state)
