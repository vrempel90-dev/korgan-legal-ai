from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from korgan import bot as base_bot
from korgan.ui import main_menu

router = Router(name="korgan-reply-main-menu")


@router.message(F.text == "📄 Документ")
async def document_button(message: Message, state: FSMContext) -> None:
    # This is a normal Telegram reply-keyboard message, not a callback.
    # Reuse the existing fail-closed claim generator directly.
    await base_bot.claim_handler(message, state)


@router.message(F.text == "⚖️ Консультация")
async def consultation_button(message: Message) -> None:
    await message.answer(
        "⚖️ Опишите ситуацию одним сообщением. Если есть документы или сканы — просто отправьте их в этот чат.",
        reply_markup=main_menu(),
    )


@router.message(F.text == "📦 Моё дело")
async def case_button(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    docs = data.get("documents", []) or []
    facts = data.get("facts", []) or []
    await message.answer(
        f"📦 Моё дело\n\nДокументов / сканов: {len(docs)}\nТекстовых описаний: {len(facts)}\n\n"
        "Чтобы добавить материал — просто отправьте файл, фото или текст. Для генерации нажмите «📄 Документ».",
        reply_markup=main_menu(),
    )


@router.message(F.text == "💰 Цены")
async def prices_button(message: Message) -> None:
    await message.answer(
        "💰 Сейчас идёт тестирование генерации документов. Оплата временно отключена.",
        reply_markup=main_menu(),
    )


@router.message(F.text == "👨‍⚖️ Ваш персональный юрист")
async def lawyer_button(message: Message) -> None:
    await message.answer(
        "👨‍⚖️ Раздел подключения живого юриста будет доступен после запуска клиентского режима.",
        reply_markup=main_menu(),
    )


@router.message(F.text == "❓ Помощь и частые вопросы")
async def help_button(message: Message) -> None:
    await message.answer(
        "❓ Как работать с KORGAN:\n"
        "1. Опишите ситуацию.\n"
        "2. При необходимости отправьте PDF/DOCX/TXT, фото или сканы.\n"
        "3. Нажмите «📄 Документ».\n"
        "4. KORGAN проверит правовую основу и отправит готовый .docx либо укажет NEEDS_VERIFICATION.",
        reply_markup=main_menu(),
    )


@router.message(F.text == "🆘 Техподдержка")
async def support_button(message: Message) -> None:
    await message.answer(
        "🆘 Если файл не принимается или документ формируется некорректно, пришлите описание ошибки сюда.",
        reply_markup=main_menu(),
    )


@router.message(F.text == "⭐ Оставить отзыв")
async def feedback_button(message: Message) -> None:
    await message.answer(
        "⭐ Напишите отзыв следующим сообщением, начав его со слова «Отзыв:».",
        reply_markup=main_menu(),
    )


@router.message(F.text == "🗑 Удалить мои данные")
async def delete_button(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    language = str(data.get("language", "ru"))
    await state.set_data({"language": language, "documents": [], "facts": []})
    await message.answer("✅ Материалы текущего дела удалены.", reply_markup=main_menu())
