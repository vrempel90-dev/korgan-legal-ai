from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from korgan import bot as base_bot
from korgan.i18n import KK, normalize_language
from korgan.pipeline_invariants_v2 import exact_client_diagnostics, split_issues
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


def _all_pretrial_issues(draft, research) -> list[str]:
    issues = list(pretrial_quality_issues(draft, research))
    for note in research.notes or []:
        text = str(note or "").strip()
        if text.startswith("INTERNAL_QUALITY:"):
            issue = text.split(":", 1)[1].strip()
            if issue and issue not in issues:
                issues.append(issue)
    return issues


async def _generate(message: Message, state: FSMContext) -> None:
    await _save_text(message, state)
    # current_request_id registers this handler as the sole heavy task. A newer
    # message cancels it before another research/draft stage can start.
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
        if not await request_is_current(state, request_id, "pretrial"):
            LOGGER.info("STALE_DOCUMENT_SUPPRESSED kind=pretrial request_id=%s stage=after_research", request_id)
            return
        draft = await draft_method(context, research, language=lang)
        issues = _all_pretrial_issues(draft, research)
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

    user_issues, internal_issues = split_issues(issues)
    if user_issues:
        diagnostics = exact_client_diagnostics("pretrial", user_issues)
        LOGGER.warning(
            "PIPELINE_QUALITY_GATE kind=pretrial issues_after=%d action=BLOCK block_class=NEEDS_USER_DATA issues=%s",
            len(issues),
            user_issues[:6],
        )
        text = (
            "Претензия пока не сформирована: нужны данные, которые может предоставить только пользователь.\n\n"
            + diagnostics
        )
        await message.answer(text, reply_markup=menu)
        return

    if internal_issues:
        diagnostics = exact_client_diagnostics("pretrial", internal_issues)
        LOGGER.warning(
            "PIPELINE_QUALITY_GATE kind=pretrial issues_after=%d action=DELIVER_WITH_DIAGNOSTIC block_class=INTERNAL_QUALITY issues=%s",
            len(issues),
            internal_issues[:6],
        )
        caption = (
            "⚠️ PRELIMINARY · Проект досудебной претензии сформирован. "
            "KORGAN обнаружил внутренние вопросы качества; они не перекладываются на пользователя.\n\n"
            + diagnostics
        )
    else:
        LOGGER.info("PIPELINE_QUALITY_GATE kind=pretrial issues_after=0 action=DELIVER result=PASS")
        caption = (
            "✅ Сотқа дейінгі талап Word (.docx) форматында дайын."
            if lang == KK else
            "✅ Досудебная претензия сформирована в Word (.docx)."
        )

    filename = "KORGAN_sotqa_deyingi_talap.docx" if lang == KK else "KORGAN_dosudebnaya_pretenziya.docx"
    await message.answer_document(
        BufferedInputFile(file_bytes, filename=filename),
        caption=caption[:1000],
        reply_markup=menu,
    )


@router.callback_query(F.data == "doc:pretrial")
async def pretrial_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is not None:
        await start_new_document_request(state, kind="pretrial", mode="pretrial_waiting")
        await _ask_pretrial(callback.message, state)


@router.message(_Waiting(), F.text)
async def pretrial_waiting(message: Message, state: FSMContext) -> None:
    await _generate(message, state)


@router.message(_Intent(), F.text)
async def pretrial_natural(message: Message, state: FSMContext) -> None:
    await start_new_document_request(state, kind="pretrial", mode="main")
    await _generate(message, state)
