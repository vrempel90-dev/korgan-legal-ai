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
from korgan.material_law_guard import has_material_verified
from korgan.response_docx import build_response_to_claim_docx
from korgan.response_intent import is_response_to_claim_request
from korgan.ui import main_menu
from korgan.universal_claim_runtime import _generate_now as generate_claim_now

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
    lang = str((await state.get_data()).get("language", "ru"))
    await state.update_data(mode="contract_details")
    await message.answer(
        "🤝 Опишите договор одним сообщением: вид/цель договора, стороны и роли, предмет, цена/оплата, срок и важные условия. "
        "После этого KORGAN проверит право РК и сформирует Word.",
        reply_markup=main_menu(lang),
    )


async def _ask_response(message: Message, state: FSMContext) -> None:
    lang = str((await state.get_data()).get("language", "ru"))
    await state.update_data(mode="response_details")
    await message.answer(
        "🛡 Пришлите иск (PDF/DOCX/фото) или вставьте его требования текстом. Если можете, одним сообщением добавьте позицию ответчика, "
        "оспариваемые факты, доказательства, суд и номер дела. После этого KORGAN сформирует отзыв в Word.",
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
    menu = main_menu(lang)
    await message.answer("Формирую и проверяю договор…", reply_markup=menu)
    await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        research = await research_method(context, language=lang)
        if not has_material_verified(research):
            LOGGER.error("UNIVERSAL_CONTRACT_MATERIAL_LAW_BLOCK verified=%d", len(research.verified_claims))
            await message.answer(
                "Договор пока не прошёл юридическую проверку, поэтому Word-файл не выдан. "
                "Правовая конструкция договора должна быть подтверждена действующими материальными нормами, а не только процессуальными положениями. "
                "Попробуйте сформировать договор повторно.",
                reply_markup=menu,
            )
            return
        draft = await draft_method(context, research, language=lang)
        quality = assess_document_quality("contract", context, research, draft)
    except Exception:
        LOGGER.exception("Universal contract generation failed")
        await message.answer(
            "Не удалось безопасно сформировать договор. KORGAN не будет выдавать неподтверждённый текст как готовый документ.",
            reply_markup=menu,
        )
        return

    if not quality.ready:
        draft.status = VerificationStatus.NEEDS_VERIFICATION
        LOGGER.error(
            "UNIVERSAL_CONTRACT_RELEASE_BLOCK quality=%.1f blockers=%s issues=%s",
            quality.score,
            quality.hard_blockers[:6],
            quality.issues[:6],
        )
        await message.answer(
            "Договор пока не прошёл юридическую проверку, поэтому Word-файл не выдан. "
            "KORGAN не отправляет предварительный документ как готовый. Попробуйте сформировать договор повторно.",
            reply_markup=menu,
        )
        return

    draft.status = VerificationStatus.VERIFIED
    try:
        file_bytes = build_contract_docx(draft)
    except Exception:
        LOGGER.exception("Universal contract DOCX rendering failed")
        await message.answer("Не удалось сформировать Word-файл договора. Попробуйте повторить.", reply_markup=menu)
        return

    export_blockers = rendered_docx_blockers(file_bytes, ready_expected=True)
    if export_blockers:
        LOGGER.error("UNIVERSAL_CONTRACT_DOCX_BLOCK quality=%.1f issues=%s", quality.score, export_blockers)
        await message.answer("Готовый Word не выпущен: экспорт не прошёл финальную проверку документа.", reply_markup=menu)
        return

    await message.answer_document(
        BufferedInputFile(file_bytes, filename="KORGAN_dogovor.docx"),
        caption="✅ Договор сформирован в Word (.docx).",
        reply_markup=menu,
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
    menu = main_menu(lang)
    await message.answer("Формирую и проверяю отзыв на иск…", reply_markup=menu)
    await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        research = await research_method(context, language=lang)
        draft = await draft_method(context, research, language=lang)
        quality = assess_document_quality("response_to_claim", context, research, draft)
    except Exception:
        LOGGER.exception("Universal response-to-claim generation failed")
        await message.answer(
            "Не удалось безопасно сформировать отзыв. KORGAN не будет выдавать неподтверждённый текст как готовый документ.",
            reply_markup=menu,
        )
        return

    if not quality.ready:
        draft.status = VerificationStatus.NEEDS_VERIFICATION
        LOGGER.error(
            "UNIVERSAL_RESPONSE_RELEASE_BLOCK quality=%.1f blockers=%s issues=%s",
            quality.score,
            quality.hard_blockers[:6],
            quality.issues[:6],
        )
        await message.answer(
            "Отзыв пока не прошёл юридическую проверку, поэтому Word-файл не выдан. "
            "KORGAN не отправляет предварительный документ как готовый. Попробуйте сформировать отзыв повторно.",
            reply_markup=menu,
        )
        return

    draft.status = VerificationStatus.VERIFIED
    try:
        file_bytes = build_response_to_claim_docx(draft)
    except Exception:
        LOGGER.exception("Universal response DOCX rendering failed")
        await message.answer("Не удалось сформировать Word-файл отзыва. Попробуйте повторить.", reply_markup=menu)
        return

    export_blockers = rendered_docx_blockers(file_bytes, ready_expected=True)
    if export_blockers:
        LOGGER.error("UNIVERSAL_RESPONSE_DOCX_BLOCK quality=%.1f issues=%s", quality.score, export_blockers)
        await message.answer("Готовый Word не выпущен: экспорт не прошёл финальную проверку документа.", reply_markup=menu)
        return

    await message.answer_document(
        BufferedInputFile(file_bytes, filename="KORGAN_otzyv_na_isk.docx"),
        caption="✅ Отзыв на иск сформирован в Word (.docx).",
        reply_markup=menu,
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
    await _send_response(message, state)


@router.message(ContractRequestFilter())
async def contract_request(message: Message, state: FSMContext) -> None:
    await _send_contract(message, state)


@router.callback_query(F.data == "doc:claim")
async def claim_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is not None:
        await generate_claim_now(callback.message, state)


@router.callback_query(F.data == "doc:contract")
async def contract_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is not None:
        await _ask_contract(callback.message, state)


@router.callback_query(F.data == "doc:response")
async def response_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None:
        return
    context = await base_bot._case_context(state)
    if _looks_like_claim_materials(context):
        await _send_response(callback.message, state)
    else:
        await _ask_response(callback.message, state)
