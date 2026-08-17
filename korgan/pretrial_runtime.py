from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from korgan import bot as base_bot
from korgan.i18n import KK, normalize_language
from korgan.pretrial import (
    build_pretrial_docx,
    is_pretrial_request,
    pretrial_quality_issues,
    pretrial_release_blockers,
)
from korgan.ui import main_menu

LOGGER = logging.getLogger(__name__)
router = Router(name="korgan-pretrial-no-questionnaire")
_PRETRIAL_BUTTONS = {"📨 Досудебная претензия", "📨 Сотқа дейінгі талап"}


class _Waiting(BaseFilter):
    async def __call__(self, message: Message, state: FSMContext) -> bool:
        data = await state.get_data()
        return data.get("mode") == "pretrial_waiting" and bool(message.text) and not message.text.startswith("/")


class _Intent(BaseFilter):
    async def __call__(self, message: Message, state: FSMContext) -> bool:
        data = await state.get_data()
        if data.get("mode") in {"consultation", "contract_details", "response_details"}:
            return False
        return is_pretrial_request(message.text)


async def _lang(state: FSMContext) -> str:
    return normalize_language(str((await state.get_data()).get("language", "ru")))


async def _save_text(message: Message, state: FSMContext) -> None:
    if message.from_user is not None and message.from_user.is_bot:
        return
    text = (message.text or "").strip()
    if not text or text in _PRETRIAL_BUTTONS:
        return
    data = await state.get_data()
    facts = list(data.get("facts", []) or [])
    if not facts or str(facts[-1]).strip() != text:
        facts.append(text)
    await state.update_data(facts=facts[-20:])


async def _generate(message: Message, state: FSMContext) -> None:
    await _save_text(message, state)
    lang = await _lang(state)
    context = await base_bot._case_context(state)
    menu = main_menu(lang)

    if not context.strip():
        await state.update_data(mode="pretrial_waiting")
        prompt = (
            "Сотқа дейінгі талапты дайындау үшін жағдайды бір хабарламада сипаттаңыз немесе құжаттарды тіркеңіз. "
            "KORGAN сауалнама толтырмайды: мән-жайларды өзі шығарып, құқықтық негізді тексереді."
            if lang == KK
            else
            "Чтобы подготовить досудебную претензию, опишите ситуацию одним сообщением или приложите документы. "
            "KORGAN не будет вести анкету: сам извлечёт обстоятельства и проверит правовую основу."
        )
        await message.answer(prompt, reply_markup=menu)
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
    await message.answer(
        "Сотқа дейінгі талапты дайындап, құқықтық негізін тексеріп жатырмын…"
        if lang == KK else
        "Формирую досудебную претензию и проверяю правовую основу…",
        reply_markup=menu,
    )
    await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        research = await research_method(context, language=lang)
        draft = await draft_method(context, research, language=lang)
        issues = pretrial_quality_issues(draft, research)
        blockers = pretrial_release_blockers(draft, research, context)
    except Exception:
        LOGGER.exception("Pretrial demand generation failed")
        await message.answer(
            "Сотқа дейінгі талапты қауіпсіз қалыптастыру мүмкін болмады. Қайта көріңіз."
            if lang == KK else
            "Не удалось безопасно сформировать досудебную претензию. Попробуйте повторить.",
            reply_markup=menu,
        )
        return

    if issues:
        LOGGER.info("PRETRIAL_REVIEW issues=%s", issues[:8])
    if blockers:
        LOGGER.error("PRETRIAL_RELEASE_BLOCK blockers=%s", blockers[:8])
        await message.answer(
            (
                "Құжат құқықтық тексеруден толық өтпеді, сондықтан Word-файл берілмеді. "
                "KORGAN негізгі талаптың құқықтық негізін толық тексермей құжатты дайын деп жібермейді. Қайта дайындап көріңіз."
                if lang == KK
                else
                "Документ пока не прошёл юридическую проверку, поэтому Word-файл не выдан. "
                "KORGAN не отправляет документ как готовый, пока правовая основа основного требования не подтверждена. Попробуйте сформировать документ повторно."
            ),
            reply_markup=menu,
        )
        return

    try:
        file_bytes = build_pretrial_docx(draft, language=lang)
    except Exception:
        LOGGER.exception("Pretrial DOCX rendering failed")
        await message.answer(
            "Сотқа дейінгі талапты Word форматында қалыптастыру мүмкін болмады. Қайта көріңіз."
            if lang == KK else
            "Не удалось сформировать Word-файл досудебной претензии. Попробуйте повторить.",
            reply_markup=menu,
        )
        return

    filename = "KORGAN_sotqa_deyingi_talap.docx" if lang == KK else "KORGAN_dosudebnaya_pretenziya.docx"
    caption = (
        "✅ Сотқа дейінгі талап Word (.docx) форматында дайын."
        if lang == KK else
        "✅ Досудебная претензия сформирована в Word (.docx)."
    )
    await message.answer_document(
        BufferedInputFile(file_bytes, filename=filename),
        caption=caption,
        reply_markup=menu,
    )


@router.callback_query(F.data == "doc:pretrial")
async def pretrial_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is not None:
        await _generate(callback.message, state)


@router.message(_Waiting(), F.text)
async def pretrial_waiting(message: Message, state: FSMContext) -> None:
    await _generate(message, state)


@router.message(_Intent(), F.text)
async def pretrial_natural(message: Message, state: FSMContext) -> None:
    await _generate(message, state)
