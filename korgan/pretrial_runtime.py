from __future__ import annotations

import logging
from typing import Any

from aiogram import F, Router
from aiogram.filters import BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from korgan import bot as base_bot
from korgan.claim_intent import is_claim_drafting_request
from korgan.i18n import KK, normalize_language
from korgan.pretrial import build_pretrial_docx, pretrial_release_blockers
from korgan.ui import main_menu

LOGGER = logging.getLogger(__name__)
router = Router(name="korgan-pretrial-button-only")


class _Waiting(BaseFilter):
    async def __call__(self, message: Message, state: FSMContext) -> bool:
        data = await state.get_data()
        text = (message.text or "").strip()
        if data.get("mode") != "pretrial_waiting" or not text or text.startswith("/"):
            return False
        if is_claim_drafting_request(text):
            return False
        return True


async def _lang(state: FSMContext) -> str:
    return normalize_language(str((await state.get_data()).get("language", "ru")))


async def _save_text(state: FSMContext, text: str | None) -> None:
    value = (text or "").strip()
    if not value:
        return
    data = await state.get_data()
    facts = list(data.get("facts", []) or [])
    if not facts or str(facts[-1]).strip() != value:
        facts.append(value)
    await state.update_data(facts=facts[-20:])


async def _generate(bot: Any, chat_id: int, state: FSMContext, new_text: str | None = None) -> None:
    if new_text:
        await _save_text(state, new_text)

    lang = await _lang(state)
    menu = main_menu(lang)
    context = await base_bot._case_context(state)

    if not context.strip():
        await state.update_data(mode="pretrial_waiting")
        await bot.send_message(
            chat_id,
            "Сотқа дейінгі талапты дайындау үшін жағдайды бір хабарламада сипаттаңыз немесе құжаттарды тіркеңіз."
            if lang == KK
            else "Чтобы подготовить досудебную претензию, опишите ситуацию одним сообщением или приложите документы.",
            reply_markup=menu,
        )
        return

    service = base_bot.service
    research_method = getattr(service, "research_pretrial", None) if service is not None else None
    draft_method = getattr(service, "draft_pretrial", None) if service is not None else None
    if research_method is None or draft_method is None:
        await state.update_data(mode="main")
        await bot.send_message(
            chat_id,
            "Сотқа дейінгі талап модулі жүктелмеді." if lang == KK else "Модуль досудебной претензии не загружен.",
            reply_markup=menu,
        )
        return

    await state.update_data(mode="main")
    await bot.send_message(
        chat_id,
        "Сотқа дейінгі талапты дайындап, құқықтық негізін тексеріп жатырмын…"
        if lang == KK
        else "Формирую досудебную претензию и проверяю её правовое обоснование…",
        reply_markup=menu,
    )
    await bot.send_chat_action(chat_id, "typing")

    try:
        research = await research_method(context, language=lang)
        draft = await draft_method(context, research, language=lang)
        blockers = pretrial_release_blockers(draft, research, context)
    except Exception:
        LOGGER.exception("Pretrial demand generation failed")
        await bot.send_message(
            chat_id,
            "Сотқа дейінгі талапты қауіпсіз қалыптастыру мүмкін болмады. Қайта көріңіз."
            if lang == KK
            else "Не удалось безопасно сформировать досудебную претензию. Попробуйте повторить.",
            reply_markup=menu,
        )
        return

    if blockers:
        LOGGER.error("PRETRIAL_RELEASE_BLOCK blockers=%s", blockers[:8])
        await bot.send_message(
            chat_id,
            "Құжат жіберілмеді: негізгі талаптың құқықтық негізі толық расталмады."
            if lang == KK
            else "Документ не выдан: правовая основа основного требования подтверждена недостаточно.",
            reply_markup=menu,
        )
        return

    try:
        file_bytes = build_pretrial_docx(draft, language=lang)
    except Exception:
        LOGGER.exception("Pretrial DOCX rendering failed")
        await bot.send_message(
            chat_id,
            "Сотқа дейінгі талапты Word форматында қалыптастыру мүмкін болмады."
            if lang == KK
            else "Не удалось сформировать Word-файл досудебной претензии.",
            reply_markup=menu,
        )
        return

    filename = "KORGAN_sotqa_deyingi_talap.docx" if lang == KK else "KORGAN_dosudebnaya_pretenziya.docx"
    caption = "✅ Сотқа дейінгі талап Word (.docx) форматында дайын." if lang == KK else "✅ Досудебная претензия сформирована в Word (.docx)."
    await bot.send_document(
        chat_id,
        BufferedInputFile(file_bytes, filename=filename),
        caption=caption,
        reply_markup=menu,
    )


@router.callback_query(F.data == "doc:pretrial")
async def pretrial_button(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer("Открываю досудебную претензию…")
    chat_id = getattr(getattr(callback.message, "chat", None), "id", callback.from_user.id)
    context = await base_bot._case_context(state)
    if not context.strip():
        await state.update_data(mode="pretrial_waiting")
        lang = await _lang(state)
        await callback.bot.send_message(
            chat_id,
            "📨 Сотқа дейінгі талапты дайындау үшін жағдайды бір хабарламада сипаттаңыз немесе құжаттарды тіркеңіз."
            if lang == KK
            else "📨 Чтобы подготовить досудебную претензию, опишите ситуацию одним сообщением или приложите документы.",
            reply_markup=main_menu(lang),
        )
        return
    await _generate(callback.bot, chat_id, state)


@router.message(_Waiting(), F.text)
async def pretrial_waiting(message: Message, state: FSMContext) -> None:
    await _generate(message.bot, message.chat.id, state, new_text=message.text)
