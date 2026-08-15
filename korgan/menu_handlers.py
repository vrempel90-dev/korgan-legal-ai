from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from korgan import bot as base_bot
from korgan.ui import (
    DOCUMENTS_TEXT,
    MAIN_TEXT,
    WELCOME_TEXT,
    back_to_main,
    case_menu,
    delete_confirm_menu,
    documents_menu,
    help_menu,
    main_menu,
)

router = Router(name="korgan-inline-menu")


async def _edit(callback: CallbackQuery, text: str, markup) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return
    try:
        await message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    except TelegramBadRequest:
        await message.answer(text, parse_mode="HTML", reply_markup=markup)


async def _case_text(state: FSMContext) -> str:
    data = await state.get_data()
    docs = data.get("documents", []) or []
    facts = data.get("facts", []) or []
    return (
        "📦 <b>Моё дело</b>\n\n"
        f"📎 Загружено документов / сканов: <b>{len(docs)}</b>\n"
        f"💬 Текстовых описаний ситуации: <b>{len(facts)}</b>\n\n"
        "Можно добавить материалы или сразу перейти к подготовке иска."
    )


@router.callback_query(F.data == "menu:main")
async def main_callback(callback: CallbackQuery) -> None:
    await _edit(callback, MAIN_TEXT, main_menu())


@router.callback_query(F.data == "menu:consult")
async def consult_callback(callback: CallbackQuery) -> None:
    await _edit(
        callback,
        "⚖️ <b>Юридическая консультация</b>\n\n"
        "Опишите ситуацию одним сообщением. Если вы уже загрузили документы или сканы, KORGAN учтёт их.\n\n"
        "Точные нормы права используются только после проверки официальных источников РК.",
        back_to_main(),
    )


@router.callback_query(F.data == "menu:documents")
async def documents_callback(callback: CallbackQuery) -> None:
    await _edit(callback, DOCUMENTS_TEXT, documents_menu())


@router.callback_query(F.data == "menu:case")
async def case_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await _edit(callback, await _case_text(state), case_menu())


@router.callback_query(F.data == "menu:prices")
async def prices_callback(callback: CallbackQuery) -> None:
    await _edit(
        callback,
        "💰 <b>Цены KORGAN</b>\n\n"
        "🧪 Сейчас идёт тестирование генерации юридических документов.\n"
        "Оплата временно отключена. Финальные тарифы будут подключены после проверки качества.",
        back_to_main(),
    )


@router.callback_query(F.data == "menu:lawyer")
async def lawyer_callback(callback: CallbackQuery) -> None:
    await _edit(
        callback,
        "👨‍⚖️ <b>Ваш персональный юрист</b>\n\n"
        "Раздел для передачи сложного вопроса живому юристу KORGAN.\n"
        "Подключение специалиста будет доступно после запуска клиентского режима.",
        back_to_main(),
    )


@router.callback_query(F.data == "menu:help")
async def help_callback(callback: CallbackQuery) -> None:
    await _edit(callback, "❓ <b>Помощь и частые вопросы</b>\n\nВыберите раздел:", help_menu())


@router.callback_query(F.data == "menu:support")
async def support_callback(callback: CallbackQuery) -> None:
    await _edit(
        callback,
        "🆘 <b>Техподдержка</b>\n\n"
        "Если KORGAN не принимает файл, не отвечает или документ формируется некорректно — сообщите об ошибке администратору проекта.",
        back_to_main(),
    )


@router.callback_query(F.data == "menu:feedback")
async def feedback_callback(callback: CallbackQuery) -> None:
    await _edit(
        callback,
        "⭐ <b>Оставить отзыв</b>\n\n"
        "Напишите отзыв обычным сообщением, начав его со слова «Отзыв:». Спасибо за обратную связь.",
        back_to_main(),
    )


@router.callback_query(F.data == "menu:delete")
async def delete_callback(callback: CallbackQuery) -> None:
    await _edit(
        callback,
        "🗑 <b>Удалить мои данные</b>\n\n"
        "Будут удалены материалы и текстовые факты текущей Telegram-сессии. Продолжить?",
        delete_confirm_menu(),
    )


@router.callback_query(F.data == "delete:confirm")
async def delete_confirm_callback(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    language = str(data.get("language", "ru"))
    await state.set_data({"language": language, "documents": [], "facts": []})
    await _edit(callback, "✅ Данные текущего дела удалены.", main_menu())


@router.callback_query(F.data == "doc:upload")
async def upload_callback(callback: CallbackQuery) -> None:
    await _edit(
        callback,
        "📎 <b>Загрузка документов</b>\n\n"
        "Отправьте сюда PDF, DOCX, TXT, JPG, PNG, WEBP или фотографию документа.\n\n"
        "KORGAN извлечёт необходимые для дела факты и сохранит их в текущей сессии.",
        documents_menu(),
    )


@router.callback_query(F.data == "doc:case")
async def document_case_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await _edit(callback, await _case_text(state), case_menu())


@router.callback_query(F.data == "doc:clear")
async def document_clear_callback(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    language = str(data.get("language", "ru"))
    await state.set_data({"language": language, "documents": [], "facts": []})
    await _edit(callback, "🧹 Текущее дело очищено.", documents_menu())


@router.callback_query(F.data == "doc:claim")
async def claim_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    message = callback.message
    if isinstance(message, Message):
        await base_bot.claim_handler(message, state)


@router.callback_query(F.data == "help:capabilities")
async def capabilities_callback(callback: CallbackQuery) -> None:
    await _edit(
        callback,
        "⚖️ <b>Что умеет KORGAN</b>\n\n"
        "• консультировать по праву Республики Казахстан;\n"
        "• принимать документы и сканы;\n"
        "• извлекать стороны, даты, суммы и другие факты;\n"
        "• готовить проект искового заявления;\n"
        "• проверять правовые основания по официальным источникам.",
        help_menu(),
    )


@router.callback_query(F.data == "help:claim")
async def claim_help_callback(callback: CallbackQuery) -> None:
    await _edit(
        callback,
        "📄 <b>Как подготовить иск</b>\n\n"
        "1. Опишите ситуацию.\n"
        "2. Загрузите договоры, квитанции и другие доказательства.\n"
        "3. Откройте «Документы» → «Исковое заявление».\n"
        "4. KORGAN проверит правовую основу и сформирует DOCX либо укажет, что требует проверки.",
        help_menu(),
    )


@router.callback_query(F.data == "help:upload")
async def upload_help_callback(callback: CallbackQuery) -> None:
    await _edit(
        callback,
        "📎 <b>Как загрузить документ</b>\n\n"
        "Просто отправьте файл или фотографию в чат. Поддерживаются PDF, DOCX, TXT, JPG, PNG и WEBP.",
        help_menu(),
    )


@router.callback_query(F.data == "help:incomplete")
async def incomplete_callback(callback: CallbackQuery) -> None:
    await _edit(
        callback,
        "❗ <b>Документ получился неполным</b>\n\n"
        "Добавьте недостающие документы или напишите отсутствующие факты обычным сообщением, затем сформируйте иск повторно.",
        help_menu(),
    )


@router.callback_query(F.data == "help:privacy")
async def privacy_callback(callback: CallbackQuery) -> None:
    await _edit(
        callback,
        "🔐 <b>Персональные данные</b>\n\n"
        "В тестовой версии материалы дела хранятся только в памяти текущей сессии процесса и удаляются при очистке дела или перезапуске сервиса.",
        help_menu(),
    )
