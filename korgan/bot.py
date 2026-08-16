from __future__ import annotations

import asyncio
import io
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from korgan.claim_docx import build_claim_docx, missing_required_fields
from korgan.claim_failure import (
    ClaimFailure,
    ClaimFailureCode,
    ClaimStage,
    failure_from_exception,
)
from korgan.claim_intent import is_claim_drafting_request
from korgan.claim_preflight import inspect_claim_context
from korgan.config import get_settings
from korgan.document_release import review_lines
from korgan.field_intake import format_hint, normalize_answer
from korgan.telegram_text import bullets, fit_caption
from korgan.legal_corpus import extract_cited_articles
from korgan.legal_types import ExtractedDocument, VerificationStatus
from korgan.openai_legal import OpenAILegalService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
LOGGER = logging.getLogger(__name__)
router = Router()
service: OpenAILegalService | None = None

# Asking for the same field set more than twice means the pipeline is stuck.
_MAX_FIELD_REPEATS = 2

MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="⚖️ Консультация"), KeyboardButton(text="📄 Подготовить иск")],
        [KeyboardButton(text="📎 Материалы дела"), KeyboardButton(text="🗑 Очистить дело")],
    ],
    resize_keyboard=True,
)


def _split(text: str, limit: int = 4000) -> list[str]:
    parts: list[str] = []
    remaining = text.strip()
    while remaining:
        if len(remaining) <= limit:
            parts.append(remaining)
            break
        cut = remaining.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = remaining.rfind(" ", 0, limit)
        if cut <= 0:
            cut = limit
        parts.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    return parts


async def _language(state: FSMContext) -> str:
    data = await state.get_data()
    return str(data.get("language", "ru"))


async def _case_context(state: FSMContext) -> str:
    data = await state.get_data()
    docs = data.get("documents", []) or []
    facts = data.get("facts", []) or []
    consulted_articles = data.get("consulted_articles", []) or []
    chunks = [str(item) for item in docs]
    if facts:
        chunks.append("Сообщения пользователя о фактах:\n" + "\n".join(str(x) for x in facts[-12:]))
    if consulted_articles:
        chunks.append(
            "Нормы, упомянутые в предыдущей консультации KORGAN — ТОЛЬКО поисковые подсказки; "
            "перед включением в документ их нужно заново подтвердить source-bound поиском по официальному источнику:\n"
            + "; ".join(str(x) for x in consulted_articles[-20:])
        )
    return "\n\n---\n\n".join(chunks)


async def _save_document(state: FSMContext, extracted: ExtractedDocument) -> int:
    settings = get_settings()
    data = await state.get_data()
    docs = list(data.get("documents", []) or [])
    docs.append(extracted.as_context())
    docs = docs[-settings.max_case_documents :]
    await state.update_data(documents=docs)
    return len(docs)


@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    await state.set_data({"language": "ru", "documents": [], "facts": [], "consulted_articles": [], "mode": "main"})
    await message.answer(
        "⚖️ KORGAN Legal AI\n\n"
        "Я работаю по законодательству Республики Казахстан. Можно отправить PDF/DOCX/TXT, фото или скан документа — "
        "я извлеку факты и сохраню их в материалах текущего дела. Затем попросите подготовить иск.\n\n"
        "Точные статьи, сроки, госпошлина и подсудность используются только после проверки официального источника; "
        "если подтверждения нет — будет NEEDS_VERIFICATION.\n\n"
        "/ru — русский, /kk — қазақша, /claim — подготовить иск, /clear — очистить дело.",
        reply_markup=MENU,
    )


@router.message(Command("ru"))
async def set_ru(message: Message, state: FSMContext) -> None:
    await state.update_data(language="ru")
    await message.answer("Русский язык выбран.", reply_markup=MENU)


@router.message(Command("kk"))
async def set_kk(message: Message, state: FSMContext) -> None:
    await state.update_data(language="kk")
    await message.answer("Қазақ тілі таңдалды.", reply_markup=MENU)


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(
        "1) Опишите ситуацию. 2) Прикрепите материалы дела. 3) Напишите «подготовить иск». "
        "KORGAN пришлёт готовый файл Word (.docx). Поддерживаются PDF, DOCX, TXT, JPG, JPEG, PNG, WEBP.",
        reply_markup=MENU,
    )


@router.message(Command("clear"))
@router.message(F.text == "🗑 Очистить дело")
async def clear_case(message: Message, state: FSMContext) -> None:
    lang = await _language(state)
    await state.set_data({"language": lang, "documents": [], "facts": [], "consulted_articles": [], "mode": "main"})
    await message.answer("Материалы текущего дела удалены из сессии.", reply_markup=MENU)


@router.message(F.text == "📎 Материалы дела")
async def show_case(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    docs = data.get("documents", []) or []
    facts = data.get("facts", []) or []
    await message.answer(
        f"Сейчас в деле: документов/сканов — {len(docs)}, текстовых описаний — {len(facts)}.\n"
        "Пришлите дополнительные материалы или попросите подготовить иск.",
        reply_markup=MENU,
    )


async def _analyze_upload(message: Message, state: FSMContext, data: bytes, filename: str, mime_type: str | None) -> None:
    global service
    if service is None:
        return
    await message.bot.send_chat_action(message.chat.id, "typing")
    try:
        extracted = await service.extract_document(data, filename, mime_type)
    except ValueError as exc:
        await message.answer(str(exc), reply_markup=MENU)
        return
    except Exception:
        LOGGER.exception("Document analysis failed")
        await message.answer("Не удалось разобрать документ. Проверьте формат/качество и попробуйте ещё раз.", reply_markup=MENU)
        return
    count = await _save_document(state, extracted)
    preview = extracted.as_context()
    await message.answer(
        f"✅ Материал разобран и добавлен в дело ({count}).\n\n{preview[:3200]}\n\n"
        "Если всё верно, можно добавить ещё документы или попросить подготовить иск — он придёт файлом Word (.docx).",
        reply_markup=MENU,
    )


@router.message(F.photo)
async def photo_handler(message: Message, state: FSMContext) -> None:
    photo = message.photo[-1]
    stream = io.BytesIO()
    await message.bot.download(photo, destination=stream)
    await _analyze_upload(message, state, stream.getvalue(), f"photo_{photo.file_unique_id}.jpg", "image/jpeg")


@router.message(F.document)
async def document_handler(message: Message, state: FSMContext) -> None:
    document = message.document
    filename = document.file_name or f"document_{document.file_unique_id}"
    stream = io.BytesIO()
    await message.bot.download(document, destination=stream)
    await _analyze_upload(message, state, stream.getvalue(), filename, document.mime_type)


async def _report_claim_failure(message: Message, failure: ClaimFailure) -> None:
    """Записать причину отказа в лог и назвать её пользователю."""
    LOGGER.error(failure.log_line(), exc_info=True)
    await message.answer(failure.user_message(), reply_markup=MENU)


def _intake_escape_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Начать дело заново", callback_data="intake:restart")],
            [InlineKeyboardButton(text="👨‍⚖️ Передать юристу-человеку", callback_data="intake:human")],
        ]
    )


async def _handle_missing_field_answer(message: Message, state: FSMContext, data: dict) -> None:
    """Record an answer to the "missing fields" prompt, then re-check the case.

    The order matters and is asserted by tests: parse → write to state → await
    the write → re-read the case → decide. Reusing the snapshot taken at the top
    of the handler would re-check the case as it was *before* the answer, which
    is one of the ways this loop can come back.
    """
    pending = list(data.get("pending_fields", []) or [])
    answer = message.text or ""
    intake = normalize_answer(pending, answer)

    facts = list(data.get("facts", []) or [])
    facts.append(intake.as_case_text() or answer)
    await state.update_data(facts=facts[-20:])

    if not intake.progressed:
        # Nothing was recognised. Saying what could not be read — with an
        # example — is the whole difference between a dialogue and the loop:
        # repeating the original prompt here is what made the bot look deaf.
        failures = int(data.get("intake_failures", 0) or 0) + 1
        await state.update_data(intake_failures=failures)
        LOGGER.info(
            "CLAIM_INTAKE_REJECTED received=%r pending=%s errors=%s leftover=%s failures=%d",
            answer, pending, intake.errors, intake.leftover, failures,
        )
        problem = "\n".join(intake.errors[:4]) or (
            "Не получилось распознать в вашем сообщении ни одно из запрошенных полей."
        )
        hint = format_hint(pending)
        if failures >= _MAX_FIELD_REPEATS:
            LOGGER.warning("CLAIM_INTAKE_LOOP pending=%s failures=%d", pending, failures)
            await message.answer(
                f"{problem}\n\nПришлите данные подписанными, каждое с новой строки:\n\n{hint}\n\n"
                "Если не помогает — можно начать дело заново или передать его юристу-человеку.",
                reply_markup=_intake_escape_menu(),
            )
            return
        text = "\n\n".join(part for part in [problem, hint and f"Пример:\n{hint}"] if part)
        await message.answer(text, reply_markup=MENU)
        return

    await state.update_data(intake_failures=0)

    # Re-read the case only after the write completed, so the check sees the
    # answer that was just recorded.
    context = await _case_context(state)
    remaining = inspect_claim_context(context).missing
    LOGGER.info(
        "CLAIM_INTAKE received=%r matched=%s recorded=%s errors=%s leftover=%s "
        "pending_before=%s missing_after=%s",
        answer,
        intake.matched,
        intake.recorded,
        intake.errors,
        intake.leftover,
        pending,
        list(remaining),
    )

    if intake.errors:
        await message.answer("\n".join(intake.errors[:3]), reply_markup=MENU)

    await claim_handler(message, state)


@router.callback_query(F.data == "intake:restart")
async def intake_restart(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    lang = await _language(state)
    await state.set_data({"language": lang, "documents": [], "facts": [], "consulted_articles": [], "mode": "main"})
    if callback.message is not None:
        await callback.message.answer(
            "Дело очищено. Опишите ситуацию заново одним сообщением — и я подготовлю иск.",
            reply_markup=MENU,
        )


@router.callback_query(F.data == "intake:human")
async def intake_human(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.update_data(mode="main")
    if callback.message is not None:
        await callback.message.answer(
            "Передаю запрос юристу-человеку. Опишите одним сообщением, что нужно сделать, "
            "и приложите имеющиеся документы — специалист свяжется с вами.",
            reply_markup=MENU,
        )


@router.message(Command("claim"))
@router.message(F.text == "📄 Подготовить иск")
async def claim_handler(message: Message, state: FSMContext) -> None:
    global service
    if service is None:
        return

    context = await _case_context(state)
    if not context.strip():
        await state.update_data(mode="main")
        await message.answer(
            "Сначала опишите ситуацию или пришлите документы/сканы. Без фактов я не буду придумывать иск.",
            reply_markup=MENU,
        )
        return

    preflight = inspect_claim_context(context)
    if not preflight.ready:
        data = await state.get_data()
        missing = list(preflight.missing)
        # Asking for the same set again means the previous answer changed
        # nothing. That is a defect signal, not patience — a user who answered
        # twice will answer a third time to the same wall.
        repeats = int(data.get("intake_repeats", 0) or 0)
        repeats = repeats + 1 if list(data.get("pending_fields", []) or []) == missing else 0
        LOGGER.info(
            "CLAIM_PREFLIGHT_MISSING fields=%s repeats=%d context_chars=%d",
            missing, repeats, len(context),
        )
        await state.update_data(mode="claim_details", pending_fields=missing, intake_repeats=repeats)

        if repeats >= _MAX_FIELD_REPEATS:
            LOGGER.warning("CLAIM_INTAKE_LOOP fields=%s repeats=%d", missing, repeats)
            hint = format_hint(missing)
            await message.answer(
                "Кажется, я не могу распознать присланные данные — спрашиваю одно и то же уже "
                f"{repeats + 1} раз(а). Пришлите их подписанными, каждое с новой строки:\n\n{hint}\n\n"
                "Если не помогает — можно начать дело заново или передать его юристу-человеку.",
                reply_markup=_intake_escape_menu(),
            )
            return

        await message.answer(preflight.user_message(), reply_markup=MENU)
        return

    await state.update_data(mode="main", pending_fields=[], intake_repeats=0)
    lang = await _language(state)
    await message.answer("Проверяю право и формирую Word-документ…")
    await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        research = await service.research_case(context, language=lang)
    except Exception as exc:
        await _report_claim_failure(message, failure_from_exception(exc, stage=ClaimStage.RESEARCH))
        return

    try:
        draft = await service.draft_claim(context, research, language=lang)
    except Exception as exc:
        await _report_claim_failure(message, failure_from_exception(exc, stage=ClaimStage.DRAFT))
        return

    absent = missing_required_fields(draft)
    if absent:
        await state.update_data(mode="claim_details")
        await _report_claim_failure(
            message,
            ClaimFailure(
                stage=ClaimStage.RENDER,
                code=ClaimFailureCode.MISSING_DOCUMENT_FIELD,
                fields=absent,
            ),
        )
        return

    try:
        file_bytes = build_claim_docx(draft)
    except Exception as exc:
        await _report_claim_failure(message, failure_from_exception(exc, stage=ClaimStage.RENDER))
        return

    LOGGER.info(
        "CLAIM_RELEASED status=%s notes=%d sources=%d",
        draft.status.value,
        len(draft.verification_notes),
        len(draft.source_urls),
    )

    # Release gate: re-verify every citation in the finished text and check the
    # text for truncation damage before the file reaches the user.
    report = review_lines(
        [
            draft.title,
            *draft.facts,
            *draft.legal_basis,
            draft.late_interest,
            *draft.requests,
            *draft.attachments,
        ]
    )
    if not report.released:
        LOGGER.warning("CLAIM_RELEASE_BLOCKED issues=%s", report.blocking[:5])
        await state.update_data(mode="claim_details")
        await _report_claim_failure(
            message,
            ClaimFailure(
                stage=ClaimStage.RENDER,
                code=ClaimFailureCode.QA_BLOCKED,
                issues=report.blocking[:6],
            ),
        )
        return

    marker = "✅ VERIFIED" if draft.status == VerificationStatus.VERIFIED else "⚠️ NEEDS_VERIFICATION"
    checklist = report.checklist(draft.verification_notes)
    caption = f"{marker}\nГотовый проект иска — файл Word (.docx)."
    if checklist:
        caption += "\n\nПеред подачей проверьте:\n" + bullets(checklist)
    await message.answer_document(
        BufferedInputFile(file_bytes, filename="KORGAN_iskovoe_zayavlenie.docx"),
        caption=fit_caption(caption),
        reply_markup=MENU,
    )


@router.message(F.text == "⚖️ Консультация")
async def consultation_prompt(message: Message, state: FSMContext) -> None:
    await state.update_data(mode="consultation")
    await message.answer("Опишите вопрос одним сообщением. Если по делу уже загружены документы, я учту их.", reply_markup=MENU)


@router.message(F.text)
async def legal_question(message: Message, state: FSMContext) -> None:
    global service
    if service is None or not message.text:
        return
    if message.text.startswith("/"):
        return

    data = await state.get_data()

    if data.get("mode") == "claim_details":
        await _handle_missing_field_answer(message, state, data)
        return

    explicit_consultation = data.get("mode") == "consultation"

    if is_claim_drafting_request(message.text) and not explicit_consultation:
        LOGGER.info("CLAIM_INTENT_FORCED_TO_DOCX telegram_user_id=%s", message.from_user.id if message.from_user else None)
        await claim_handler(message, state)
        return

    facts = list(data.get("facts", []) or [])
    facts.append(message.text)
    await state.update_data(facts=facts[-20:], mode="main")
    context = await _case_context(state)
    lang = await _language(state)
    await message.bot.send_chat_action(message.chat.id, "typing")
    try:
        answer, urls = await service.consult(message.text, case_context=context, language=lang)
    except Exception:
        LOGGER.exception("Consultation failed")
        await message.answer("Не удалось выполнить юридический поиск. Попробуйте повторить вопрос.", reply_markup=MENU)
        return

    # Preserve only article labels as hints for the next research pass. They are
    # never treated as VERIFIED merely because a previous consultation cited them.
    if urls:
        cited = extract_cited_articles(answer)
        if cited:
            refreshed = await state.get_data()
            previous = list(refreshed.get("consulted_articles", []) or [])
            for item in cited:
                if item not in previous:
                    previous.append(item)
            await state.update_data(consulted_articles=previous[-20:])

    sources = ""
    if urls:
        sources = "\n\nОфициальные источники:\n" + "\n".join(f"• {url}" for url in urls[:5])
    for part in _split(answer + sources):
        await message.answer(part, disable_web_page_preview=True, reply_markup=MENU)


async def main() -> None:
    global service
    settings = get_settings()
    service = OpenAILegalService(settings)
    bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    LOGGER.info("Starting KORGAN Legal AI polling (OpenAI-only)")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
