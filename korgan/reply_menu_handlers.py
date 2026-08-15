from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardRemove

from korgan import bot as base_bot
from korgan.claim_intent import is_claim_drafting_request
from korgan.ui import main_menu

router = Router(name="korgan-reply-main-menu")


class ClaimRequestFilter(BaseFilter):
    """Recognize claim drafting unless the user explicitly entered consultation mode."""

    async def __call__(self, message: Message, state: FSMContext) -> bool:
        data = await state.get_data()
        if data.get("mode") == "consultation":
            return False
        return is_claim_drafting_request(message.text)


async def _save_long_claim_message_as_facts(message: Message, state: FSMContext) -> None:
    """Preserve a detailed same-message case description before DOCX routing."""
    text = (message.text or "").strip()
    if not text or text == "📄 Документ" or len(text) < 80:
        return
    data = await state.get_data()
    facts = list(data.get("facts", []) or [])
    if not facts or facts[-1] != text:
        facts.append(text)
    await state.update_data(facts=facts[-20:])


async def _send_claim_as_word(message: Message, state: FSMContext) -> None:
    """A claim request must end in a DOCX file, never in a full chat-text claim."""
    context = await base_bot._case_context(state)
    if not context.strip():
        # A user may describe the whole case and ask for a claim in one message.
        # The claim-intent router runs before the generic text handler, so save
        # that detailed message here instead of losing it.
        await _save_long_claim_message_as_facts(message, state)
        context = await base_bot._case_context(state)

    if not context.strip():
        await message.answer(
            "📄 Сначала опишите обстоятельства дела или пришлите документы/сканы. После этого попросите подготовить иск — KORGAN пришлёт его файлом Word (.docx).",
            reply_markup=main_menu(),
        )
        return

    await state.update_data(mode="main")
    # The global consent gate has already protected this message. The generated
    # file itself contains the KORGAN draft notice, while verification warnings
    # are returned in the Telegram caption.
    await base_bot.claim_handler(message, state)


@router.message(ClaimRequestFilter())
async def natural_language_claim_request(message: Message, state: FSMContext) -> None:
    await _send_claim_as_word(message, state)


@router.message(F.text == "📄 Документ")
async def document_button(message: Message, state: FSMContext) -> None:
    await state.update_data(mode="main")
    await _send_claim_as_word(message, state)


@router.message(F.text == "⚖️ Консультация")
async def consultation_button(message: Message, state: FSMContext) -> None:
    # One-shot explicit mode: the next text must reach consultation even if it
    # contains words such as «составь иск» inside the user's narrative.
    await state.update_data(mode="consultation")
    await message.answer(
        "⚖️ Опишите ситуацию одним сообщением. Если есть документы или сканы — просто отправьте их в этот чат.",
        reply_markup=main_menu(),
    )


@router.message(F.text == "📦 Моё дело")
async def case_button(message: Message, state: FSMContext) -> None:
    await state.update_data(mode="main")
    data = await state.get_data()
    docs = data.get("documents", []) or []
    facts = data.get("facts", []) or []
    await message.answer(
        f"📦 Моё дело\n\nДокументов / сканов: {len(docs)}\nТекстовых описаний: {len(facts)}\n\n"
        "Чтобы добавить материал — просто отправьте файл, фото или текст. Для генерации нажмите «📄 Документ» "
        "или попросите KORGAN подготовить/составить иск обычным сообщением.",
        reply_markup=main_menu(),
    )


@router.message(F.text == "💰 Цены")
async def prices_button(message: Message, state: FSMContext) -> None:
    await state.update_data(mode="main")
    await message.answer("💰 Сейчас идёт тестирование генерации документов. Оплата временно отключена.", reply_markup=main_menu())


@router.message(F.text == "👨‍⚖️ Ваш персональный юрист")
async def lawyer_button(message: Message, state: FSMContext) -> None:
    await state.update_data(mode="main")
    await message.answer("👨‍⚖️ Раздел подключения живого юриста будет доступен после запуска клиентского режима.", reply_markup=main_menu())


@router.message(F.text == "❓ Помощь и частые вопросы")
async def help_button(message: Message, state: FSMContext) -> None:
    await state.update_data(mode="main")
    await message.answer(
        "❓ Как работать с KORGAN:\n"
        "1. Опишите ситуацию.\n"
        "2. При необходимости отправьте PDF/DOCX/TXT, фото или сканы.\n"
        "3. Напишите, например, «подготовь мне иск» или нажмите «📄 Документ».\n"
        "4. KORGAN проверит правовую основу и пришлёт готовый файл Word (.docx).\n"
        "5. Если часть нормы нельзя подтвердить, это будет отдельно отмечено как NEEDS_VERIFICATION.\n\n"
        "Условия: /terms\nКонфиденциальность: /privacy",
        reply_markup=main_menu(),
    )


@router.message(F.text == "🆘 Техподдержка")
async def support_button(message: Message, state: FSMContext) -> None:
    await state.update_data(mode="main")
    await message.answer("🆘 Если файл не принимается или документ формируется некорректно, пришлите описание ошибки сюда.", reply_markup=main_menu())


@router.message(F.text == "⭐ Оставить отзыв")
async def feedback_button(message: Message, state: FSMContext) -> None:
    await state.update_data(mode="main")
    await message.answer("⭐ Напишите отзыв следующим сообщением, начав его со слова «Отзыв:».", reply_markup=main_menu())


@router.message(F.text == "🗑 Удалить мои данные")
async def delete_button(message: Message, state: FSMContext) -> None:
    await state.set_data({"language": "ru", "documents": [], "facts": [], "mode": "main", "terms_accepted": False})
    await message.answer(
        "✅ Материалы текущего дела и согласие текущей сессии удалены. Для дальнейшего использования KORGAN снова откройте /start и примите актуальные условия.",
        reply_markup=ReplyKeyboardRemove(),
    )
