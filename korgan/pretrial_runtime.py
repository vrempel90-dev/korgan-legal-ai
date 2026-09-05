from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from korgan import bot as base_bot
from korgan.document_type_routing import intent_may_switch
from korgan.i18n import KK, normalize_language
from korgan.pretrial import build_pretrial_docx, is_pretrial_request, pretrial_quality_issues
from korgan.request_scope import (
    current_request_id,
    is_main_menu_text,
    request_is_current,
    request_label,
    start_new_document_request,
)
from korgan.ui import main_menu

LOGGER = logging.getLogger(__name__)
router = Router(name="korgan-pretrial-no-questionnaire")
_PRETRIAL_BUTTONS = {"📨 Досудебная претензия", "📨 Сотқа дейінгі талап"}


class _Waiting(BaseFilter):
    async def __call__(self, message: Message, state: FSMContext) -> bool:
        data = await state.get_data()
        text = message.text or ""
        return (
            data.get("mode") == "pretrial_waiting"
            and bool(text)
            and not text.startswith("/")
            and not is_main_menu_text(text)
        )


class _Intent(BaseFilter):
    async def __call__(self, message: Message, state: FSMContext) -> bool:
        data = await state.get_data()
        if data.get("mode") in {"consultation", "contract_details", "response_details"}:
            return False
        # Выбранный кнопкой раздел старше любого слова в фабуле дела.
        if not intent_may_switch(data, "pretrial"):
            return False
        return is_pretrial_request(message.text)


async def _lang(state: FSMContext) -> str:
    return normalize_language(str((await state.get_data()).get("language", "ru")))


async def _save_text(message: Message, state: FSMContext) -> None:
    if message.from_user is not None and message.from_user.is_bot:
        return
    text = (message.text or "").strip()
    if not text or text in _PRETRIAL_BUTTONS or is_main_menu_text(text):
        return
    data = await state.get_data()
    facts = list(data.get("facts", []) or [])
    if not facts or str(facts[-1]).strip() != text:
        facts.append(text)
    await state.update_data(facts=facts[-20:])


async def _ask_pretrial(message: Message, state: FSMContext) -> None:
    """Open a fresh pretrial request without starting generation."""
    lang = await _lang(state)
    await state.update_data(mode="pretrial_waiting")
    prompt = (
        f"🆕 Жаңа өтінім — {request_label('pretrial', lang)}.\n\n"
        "Жағдайды бір хабарламада сипаттаңыз немесе материалдарды (PDF/DOCX/фото) тіркеңіз. "
        "Алдыңғы өтінімнің деректері бұл өтінімге қолданылмайды."
        if lang == KK
        else
        f"🆕 Новая заявка — {request_label('pretrial', lang)}.\n\n"
        "Опишите ситуацию одним сообщением или приложите материалы (PDF/DOCX/фото). "
        "Данные предыдущей заявки сюда не переносятся."
    )
    await message.answer(prompt, reply_markup=main_menu(lang))


async def _generate(message: Message, state: FSMContext) -> None:
    await _save_text(message, state)
    request_id = await current_request_id(state, "pretrial")
    lang = await _lang(state)
    context = await base_bot._case_context(state)
    menu = main_menu(lang)

    if not context.strip():
        await _ask_pretrial(message, state)
        return

    service = base_bot.service
    research_method = getattr(service, "research_pretrial", None) if service is not None else None
    draft_method = getattr(service, "draft_pretrial", None) if service is not None else None
    if research_method is None or draft_method is None:
        await message.answer(
            "Сотқа дейінгі талап модулі жүктелмеді." if lang == KK else "Модуль досудебной претензии не загружен.",
            reply_markup=menu,
        )
        return

    await state.update_data(mode="main")
    await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        research = await research_method(context, language=lang)
        draft = await draft_method(context, research, language=lang)
        issues = pretrial_quality_issues(draft, research)
        file_bytes = build_pretrial_docx(draft, language=lang)
    except Exception:
        LOGGER.exception("Pretrial demand generation failed")
        if not await request_is_current(state, request_id, "pretrial"):
            LOGGER.info("STALE_DOCUMENT_SUPPRESSED kind=pretrial request_id=%s", request_id)
            return
        await message.answer(
            "Сотқа дейінгі талапты қауіпсіз қалыптастыру мүмкін болмады. Қайта көріңіз."
            if lang == KK else
            "Не удалось безопасно сформировать досудебную претензию. Попробуйте повторить.",
            reply_markup=menu,
        )
        return

    if not await request_is_current(state, request_id, "pretrial"):
        LOGGER.info("STALE_DOCUMENT_SUPPRESSED kind=pretrial request_id=%s", request_id)
        return

    if issues:
        LOGGER.warning("PRETRIAL_PRELIMINARY issues=%s", issues[:6])
        caption = (
            "✅ Сотқа дейінгі талаптың жобасы Word (.docx) форматында дайын. Жіберер алдында деректемелер мен сомаларды тексеріңіз."
            if lang == KK else
            "✅ Проект досудебной претензии сформирован в Word (.docx). Перед направлением проверьте реквизиты и суммы."
        )
    else:
        caption = (
            "✅ Сотқа дейінгі талап Word (.docx) форматында дайын."
            if lang == KK else
            "✅ Досудебная претензия сформирована в Word (.docx)."
        )

    filename = "KORGAN_sotqa_deyingi_talap.docx" if lang == KK else "KORGAN_dosudebnaya_pretenziya.docx"
    await message.answer_document(
        BufferedInputFile(file_bytes, filename=filename),
        caption=caption,
        reply_markup=menu,
    )


@router.callback_query(F.data == "doc:pretrial")
async def pretrial_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is not None:
        await start_new_document_request(state, kind="pretrial", mode="pretrial_waiting")
        # A menu click only opens a fresh request. Never pass the bot's callback
        # message into the generator: generation/payment must require new client input.
        await _ask_pretrial(callback.message, state)


@router.message(_Waiting(), F.text)
async def pretrial_waiting(message: Message, state: FSMContext) -> None:
    await _generate(message, state)


@router.message(_Intent(), F.text)
async def pretrial_natural(message: Message, state: FSMContext) -> None:
    await start_new_document_request(state, kind="pretrial", mode="main")
    await _generate(message, state)
