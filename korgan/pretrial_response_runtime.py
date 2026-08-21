from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.filters import BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from korgan import bot as base_bot
from korgan.i18n import KK, normalize_language
from korgan.pretrial_response import (
    build_pretrial_response_docx,
    generate_pretrial_response,
    is_pretrial_response_request,
    pretrial_response_quality_issues,
)
from korgan.ui import main_menu

LOGGER = logging.getLogger(__name__)
router = Router(name="korgan-pretrial-response")
_RESPONSE_BUTTONS = {"↩️ Ответ на претензию", "↩️ Сотқа дейінгі талапқа жауап"}


class _Waiting(BaseFilter):
    async def __call__(self, message: Message, state: FSMContext) -> bool:
        data = await state.get_data()
        return data.get("mode") == "pretrial_response_waiting" and bool(message.text) and not message.text.startswith("/")


class _Intent(BaseFilter):
    async def __call__(self, message: Message, state: FSMContext) -> bool:
        data = await state.get_data()
        if data.get("mode") in {"consultation", "contract_details", "response_details", "pretrial_waiting"}:
            return False
        return is_pretrial_response_request(message.text)


async def _lang(state: FSMContext) -> str:
    return normalize_language(str((await state.get_data()).get("language", "ru")))


async def _save_text(message: Message, state: FSMContext) -> None:
    if message.from_user is not None and message.from_user.is_bot:
        return
    text = (message.text or "").strip()
    if not text or text in _RESPONSE_BUTTONS:
        return
    data = await state.get_data()
    facts = list(data.get("facts", []) or [])
    if not facts or str(facts[-1]).strip() != text:
        facts.append(text)
    await state.update_data(facts=facts[-20:])


def _looks_like_pretrial_materials(context: str) -> bool:
    value = " ".join((context or "").split()).lower()
    return bool(
        re.search(r"\b(?:досудебн\w*\s+)?претензи\w*\b", value)
        or re.search(r"\bсотқа\s+дейінгі\s+талап\w*\b", value)
        or re.search(r"\bталап\s+хат\w*\b", value)
    )


async def _ask_for_pretrial(message: Message, state: FSMContext) -> None:
    lang = await _lang(state)
    await state.update_data(mode="pretrial_response_waiting")
    await message.answer(
        (
            "↩️ Сотқа дейінгі талапқа жауап дайындау үшін алынған талапты (PDF/DOCX/фото) жіберіңіз немесе мәтінін енгізіңіз. "
            "Мүмкін болса, қай талаптарды мойындайтыныңызды немесе дауласаңыз және қандай дәлелдер бар екенін бір хабарламада жазыңыз."
            if lang == KK
            else
            "↩️ Чтобы подготовить ответ на претензию, пришлите полученную претензию (PDF/DOCX/фото) или вставьте её текст. "
            "Если можете, одним сообщением укажите, какие требования признаёте или оспариваете и какие у вас есть доказательства."
        ),
        reply_markup=main_menu(lang),
    )


async def _generate(message: Message, state: FSMContext) -> None:
    await _save_text(message, state)
    lang = await _lang(state)
    menu = main_menu(lang)
    context = await base_bot._case_context(state)

    if not context.strip() or not _looks_like_pretrial_materials(context):
        await _ask_for_pretrial(message, state)
        return

    service = base_bot.service
    if service is None:
        await message.answer(
            "Сотқа дейінгі талапқа жауап модулі жүктелмеді." if lang == KK else "Модуль ответа на претензию не загружен.",
            reply_markup=menu,
        )
        return

    await state.update_data(mode="main")
    await message.answer(
        "Сотқа дейінгі талапты талдап, жауапты дайындап жатырмын…"
        if lang == KK
        else "Анализирую полученную претензию и формирую ответ…",
        reply_markup=menu,
    )
    await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        draft, research = await generate_pretrial_response(service, context, language=lang)
        issues = pretrial_response_quality_issues(draft, research)
        file_bytes = build_pretrial_response_docx(draft, language=lang)
    except Exception:
        LOGGER.exception("Pretrial response generation failed")
        await message.answer(
            "Сотқа дейінгі талапқа жауапты қауіпсіз қалыптастыру мүмкін болмады. Қайта көріңіз."
            if lang == KK
            else "Не удалось безопасно сформировать ответ на претензию. Попробуйте повторить.",
            reply_markup=menu,
        )
        return

    if issues:
        LOGGER.warning("PRETRIAL_RESPONSE_PRELIMINARY issues=%s", issues[:6])
        caption = (
            "✅ Сотқа дейінгі талапқа жауап жобасы Word (.docx) форматында дайын. Жіберер алдында деректерді тексеріңіз."
            if lang == KK
            else "✅ Проект ответа на претензию сформирован в Word (.docx). Перед направлением проверьте реквизиты и позицию."
        )
    else:
        caption = (
            "✅ Сотқа дейінгі талапқа жауап Word (.docx) форматында дайын."
            if lang == KK
            else "✅ Ответ на претензию сформирован в Word (.docx)."
        )

    filename = (
        "KORGAN_sotqa_deyingi_talapqa_zhauap.docx"
        if lang == KK
        else "KORGAN_otvet_na_pretenziyu.docx"
    )
    await message.answer_document(
        BufferedInputFile(file_bytes, filename=filename),
        caption=caption,
        reply_markup=menu,
    )


@router.callback_query(F.data == "doc:pretrial_response")
async def pretrial_response_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None:
        return
    context = await base_bot._case_context(state)
    if _looks_like_pretrial_materials(context):
        await _generate(callback.message, state)
    else:
        await _ask_for_pretrial(callback.message, state)


@router.message(_Waiting(), F.text)
async def pretrial_response_waiting(message: Message, state: FSMContext) -> None:
    await _generate(message, state)


@router.message(_Intent(), F.text)
async def pretrial_response_natural(message: Message, state: FSMContext) -> None:
    await _generate(message, state)
