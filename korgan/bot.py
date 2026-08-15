from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message

from korgan.config import get_settings
from korgan.legal_types import VerificationStatus
from korgan.rag import LegalRAG

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
LOGGER = logging.getLogger(__name__)
router = Router()
rag: LegalRAG | None = None


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


@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    await state.update_data(language="ru")
    await message.answer(
        "⚖️ KORGAN Legal AI\n\n"
        "Я отвечаю по законодательству Республики Казахстан и использую проверенные источники Adilet. "
        "Если точную норму подтвердить нельзя, я прямо укажу NEEDS_VERIFICATION.\n\n"
        "Команды: /ru — русский, /kk — қазақша.\nНапишите ваш юридический вопрос."
    )


@router.message(Command("ru"))
async def set_ru(message: Message, state: FSMContext) -> None:
    await state.update_data(language="ru")
    await message.answer("Русский язык выбран.")


@router.message(Command("kk"))
async def set_kk(message: Message, state: FSMContext) -> None:
    await state.update_data(language="kk")
    await message.answer("Қазақ тілі таңдалды.")


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(
        "Опишите ситуацию обычным сообщением. KORGAN найдёт релевантные нормы в индексе законодательства РК и сформирует ответ только на основе подтверждённого контекста."
    )


@router.message(F.text)
async def legal_question(message: Message, state: FSMContext) -> None:
    global rag
    if rag is None or not message.text:
        return
    lang = await _language(state)
    await message.bot.send_chat_action(message.chat.id, "typing")
    answer = await rag.answer(message.text, language=lang)

    marker = "✅ VERIFIED" if answer.status == VerificationStatus.VERIFIED else "⚠️ NEEDS_VERIFICATION"
    source_lines = []
    for source in answer.sources[:5]:
        article = f" — {source.article}" if source.article else ""
        source_lines.append(f"• {source.title}{article}\n{source.url}")
    sources = "\n\nИсточники:\n" + "\n".join(source_lines) if source_lines else ""
    response = f"{marker}\n\n{answer.text}{sources}"

    for part in _split(response):
        await message.answer(part, disable_web_page_preview=True)


async def main() -> None:
    global rag
    settings = get_settings()
    rag = LegalRAG(settings)
    bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    LOGGER.info("Starting KORGAN Legal AI polling")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
