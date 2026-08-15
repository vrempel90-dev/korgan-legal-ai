from __future__ import annotations

import asyncio
import io
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BufferedInputFile, KeyboardButton, Message, ReplyKeyboardMarkup

from korgan.claim_docx import build_claim_docx
from korgan.claim_intent import is_claim_drafting_request
from korgan.config import get_settings
from korgan.legal_types import ExtractedDocument, VerificationStatus
from korgan.openai_legal import OpenAILegalService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
LOGGER = logging.getLogger(__name__)
router = Router()
service: OpenAILegalService | None = None

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
    chunks = [str(item) for item in docs]
    if facts:
        chunks.append("Сообщения пользователя о фактах:\n" + "\n".join(str(x) for x in facts[-12:]))
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
    await state.set_data({"language": "ru", "documents": [], "facts": []})
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
    await state.set_data({"language": lang, "documents": [], "facts": []})
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


@router.message(Command("claim"))
@router.message(F.text == "📄 Подготовить иск")
async def claim_handler(message: Message, state: FSMContext) -> None:
    global service
    if service is None:
        return
    context = await _case_context(state)
    if not context.strip():
        await message.answer(
            "Сначала опишите ситуацию или пришлите документы/сканы. Без фактов я не буду придумывать иск.",
            reply_markup=MENU,
        )
        return

    lang = await _language(state)
    await message.answer("Проверяю материалы и формирую Word-документ…")
    await message.bot.send_chat_action(message.chat.id, "typing")
    try:
        research = await service.research_case(context, language=lang)
        draft = await service.draft_claim(context, research, language=lang)
        file_bytes = build_claim_docx(draft)
    except Exception:
        LOGGER.exception("Claim generation failed")
        await message.answer(
            "Не удалось безопасно сформировать Word-документ. KORGAN не будет отправлять сырой текст иска в чат. Проверьте материалы и повторите запрос.",
            reply_markup=MENU,
        )
        return

    marker = "✅ VERIFIED" if draft.status == VerificationStatus.VERIFIED else "⚠️ NEEDS_VERIFICATION"
    notes = "\n".join(f"• {x}" for x in draft.verification_notes[:10])
    caption = f"{marker}\nГотовый проект иска — файл Word (.docx)."
    if notes:
        caption += f"\n\nПеред подачей проверьте:\n{notes[:2500]}"
    await message.answer_document(
        BufferedInputFile(file_bytes, filename="KORGAN_iskovoe_zayavlenie.docx"),
        caption=caption[:1000],
        reply_markup=MENU,
    )


@router.message(F.text == "⚖️ Консультация")
async def consultation_prompt(message: Message) -> None:
    await message.answer("Опишите вопрос одним сообщением. Если по делу уже загружены документы, я учту их.", reply_markup=MENU)


@router.message(F.text)
async def legal_question(message: Message, state: FSMContext) -> None:
    global service
    if service is None or not message.text:
        return
    if message.text.startswith("/"):
        return

    # Final fail-safe: a request to PREPARE a claim must never reach the
    # consultation model. It always goes to the DOCX generator.
    if is_claim_drafting_request(message.text):
        LOGGER.info("CLAIM_INTENT_FORCED_TO_DOCX telegram_user_id=%s", message.from_user.id if message.from_user else None)
        await claim_handler(message, state)
        return

    data = await state.get_data()
    facts = list(data.get("facts", []) or [])
    facts.append(message.text)
    await state.update_data(facts=facts[-20:])
    context = await _case_context(state)
    lang = await _language(state)
    await message.bot.send_chat_action(message.chat.id, "typing")
    try:
        answer, urls = await service.consult(message.text, case_context=context, language=lang)
    except Exception:
        LOGGER.exception("Consultation failed")
        await message.answer("Не удалось выполнить юридический поиск. Попробуйте повторить вопрос.", reply_markup=MENU)
        return
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
