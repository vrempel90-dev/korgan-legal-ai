from __future__ import annotations

import re

from aiogram import F, Router
from aiogram.filters import BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardRemove

from korgan import bot as base_bot
from korgan.legal_safety import CLAIM_CONFIRM_TEXT, claim_confirmation_keyboard
from korgan.ui import main_menu

router = Router(name="korgan-reply-main-menu")


class ClaimRequestFilter(BaseFilter):
    """Recognize a user's natural-language request to prepare a court claim."""

    _pattern = re.compile(
        r"^\s*(?:пожалуйста[,\s]*)?(?:подготов(?:ь|ьте)|состав(?:ь|ьте)|сделай(?:те)?|сформируй(?:те)?|напиши(?:те)?)\s+"
        r"(?:мне\s+)?(?:исковое\s+заявление|иск)(?:\s+в\s+(?:ворде|word|docx))?[.!?\s]*$",
        re.IGNORECASE,
    )

    async def __call__(self, message: Message) -> bool:
        return bool(message.text and self._pattern.match(message.text))


async def _start_claim_document_flow(message: Message, state: FSMContext) -> None:
    """Start the protected claim-generation flow that ends with a DOCX file."""
    context = await base_bot._case_context(state)
    if not context.strip():
        await message.answer(
            "📄 Сначала опишите обстоятельства дела обычным сообщением или пришлите PDF/DOCX/TXT, фото либо скан. "
            "После этого напишите «подготовить иск» или нажмите «📄 Документ».",
            reply_markup=main_menu(),
        )
        return

    await state.update_data(claim_confirmation_pending=True)
    await message.answer(CLAIM_CONFIRM_TEXT, parse_mode="HTML", reply_markup=claim_confirmation_keyboard())


@router.message(ClaimRequestFilter())
async def natural_language_claim_request(message: Message, state: FSMContext) -> None:
    """Do not send a claim as chat text; route the request to Word generation."""
    await _start_claim_document_flow(message, state)


@router.message(F.text == "📄 Документ")
async def document_button(message: Message, state: FSMContext) -> None:
    await _start_claim_document_flow(message, state)


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
        "Чтобы добавить материал — просто отправьте файл, фото или текст. Для генерации нажмите «📄 Документ» "
        "или напишите «подготовить иск».",
        reply_markup=main_menu(),
    )


@router.message(F.text == "💰 Цены")
async def prices_button(message: Message) -> None:
    await message.answer("💰 Сейчас идёт тестирование генерации документов. Оплата временно отключена.", reply_markup=main_menu())


@router.message(F.text == "👨‍⚖️ Ваш персональный юрист")
async def lawyer_button(message: Message) -> None:
    await message.answer("👨‍⚖️ Раздел подключения живого юриста будет доступен после запуска клиентского режима.", reply_markup=main_menu())


@router.message(F.text == "❓ Помощь и частые вопросы")
async def help_button(message: Message) -> None:
    await message.answer(
        "❓ Как работать с KORGAN:\n"
        "1. Опишите ситуацию.\n"
        "2. При необходимости отправьте PDF/DOCX/TXT, фото или сканы.\n"
        "3. Напишите «подготовить иск» или нажмите «📄 Документ».\n"
        "4. Подтвердите предупреждение перед формированием.\n"
        "5. KORGAN проверит правовую основу и отправит готовый .docx либо укажет NEEDS_VERIFICATION.\n\n"
        "Условия: /terms\nКонфиденциальность: /privacy",
        reply_markup=main_menu(),
    )


@router.message(F.text == "🆘 Техподдержка")
async def support_button(message: Message) -> None:
    await message.answer("🆘 Если файл не принимается или документ формируется некорректно, пришлите описание ошибки сюда.", reply_markup=main_menu())


@router.message(F.text == "⭐ Оставить отзыв")
async def feedback_button(message: Message) -> None:
    await message.answer("⭐ Напишите отзыв следующим сообщением, начав его со слова «Отзыв:».", reply_markup=main_menu())


@router.message(F.text == "🗑 Удалить мои данные")
async def delete_button(message: Message, state: FSMContext) -> None:
    await state.set_data({"language": "ru", "documents": [], "facts": [], "terms_accepted": False})
    await message.answer(
        "✅ Материалы текущего дела и согласие текущей сессии удалены. Для дальнейшего использования KORGAN снова откройте /start и примите актуальные условия.",
        reply_markup=ReplyKeyboardRemove(),
    )
