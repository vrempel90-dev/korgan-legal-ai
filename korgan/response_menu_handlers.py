from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.filters import BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from korgan import bot as base_bot
from korgan.response_docx import build_response_to_claim_docx
from korgan.response_intent import is_response_to_claim_request
from korgan.ui import main_menu

LOGGER = logging.getLogger(__name__)
router = Router(name="korgan-response-to-claim")


class ResponseDetailsFilter(BaseFilter):
    async def __call__(self, message: Message, state: FSMContext) -> bool:
        data = await state.get_data()
        return data.get("mode") == "response_details" and bool(message.text) and not message.text.startswith("/")


class ResponseRequestFilter(BaseFilter):
    async def __call__(self, message: Message, state: FSMContext) -> bool:
        data = await state.get_data()
        if data.get("mode") in {"consultation", "contract_details"}:
            return False
        return is_response_to_claim_request(message.text)


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


async def _save_user_text(message: Message, state: FSMContext) -> None:
    if message.from_user is not None and message.from_user.is_bot:
        return
    text = (message.text or "").strip()
    if not text or text in {"📄 Документ", "🛡 Отзыв на иск"}:
        return
    data = await state.get_data()
    facts = list(data.get("facts", []) or [])
    if text not in facts[-3:]:
        facts.append(text)
    await state.update_data(facts=facts[-20:])


async def _ask_for_claim(message: Message, state: FSMContext) -> None:
    await state.update_data(mode="response_details")
    await message.answer(
        "🛡 Чтобы подготовить отзыв на иск, пришлите сам иск (PDF/DOCX/фото) или вставьте его основные требования текстом.\n\n"
        "Если можете, сразу добавьте одним сообщением:\n"
        "• что именно вы признаёте или оспариваете;\n"
        "• какие факты истца неверны;\n"
        "• какие у вас есть доказательства, платежи, переписка или документы;\n"
        "• наименование суда и номер дела, если известны.\n\n"
        "KORGAN разберёт требования истца, проверит актуальные нормы РК и сформирует отзыв в Word (.docx).",
        reply_markup=main_menu(),
    )


async def _send_response_as_word(message: Message, state: FSMContext) -> None:
    await _save_user_text(message, state)
    context = await base_bot._case_context(state)
    if not _looks_like_claim_materials(context):
        await _ask_for_claim(message, state)
        return

    service = base_bot.service
    research_method = getattr(service, "research_response_to_claim", None) if service is not None else None
    draft_method = getattr(service, "draft_response_to_claim", None) if service is not None else None
    if research_method is None or draft_method is None:
        await message.answer("Функция отзыва на иск ещё не загружена в текущую версию сервиса.", reply_markup=main_menu())
        return

    await state.update_data(mode="main")
    data = await state.get_data()
    lang = str(data.get("language", "ru"))
    await message.answer("Проверяю требования иска и актуальные нормы РК, затем формирую отзыв в Word…")
    await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        research = await research_method(context, language=lang)
        draft = await draft_method(context, research, language=lang)
        file_bytes = build_response_to_claim_docx(draft)
    except Exception:
        LOGGER.exception("Response-to-claim generation failed")
        await message.answer(
            "Не удалось сформировать отзыв из текущих материалов. Пришлите иск и позицию ответчика ещё раз — точные нормы KORGAN не будет придумывать.",
            reply_markup=main_menu(),
        )
        return

    marker = "✅ VERIFIED" if draft.status.value == "VERIFIED" else "⚠️ NEEDS_VERIFICATION"
    caption = f"{marker}\nОтзыв на иск сформирован в Word (.docx)."
    if draft.verification_notes:
        notes = "\n".join(f"• {item}" for item in draft.verification_notes[:8])
        caption += f"\n\nПеред подачей проверьте:\n{notes[:700]}"

    await message.answer_document(
        BufferedInputFile(file_bytes, filename="KORGAN_otzyv_na_isk.docx"),
        caption=caption[:1000],
        reply_markup=main_menu(),
    )


@router.message(ResponseDetailsFilter())
async def response_details_reply(message: Message, state: FSMContext) -> None:
    await _save_user_text(message, state)
    await state.update_data(mode="main")
    await _send_response_as_word(message, state)


@router.message(ResponseRequestFilter())
async def natural_language_response_request(message: Message, state: FSMContext) -> None:
    await _send_response_as_word(message, state)


@router.callback_query(F.data == "doc:response")
async def document_response_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None:
        return
    context = await base_bot._case_context(state)
    if not _looks_like_claim_materials(context):
        await _ask_for_claim(callback.message, state)
        return
    await _send_response_as_word(callback.message, state)
