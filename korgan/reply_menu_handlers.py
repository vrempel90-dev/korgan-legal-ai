from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message, ReplyKeyboardRemove

from korgan import bot as base_bot
from korgan.claim_intent import is_claim_drafting_request
from korgan.contract_docx import build_contract_docx
from korgan.contract_intent import is_contract_drafting_request
from korgan.legal_types import VerificationStatus
from korgan.ui import documents_menu, main_menu

LOGGER = logging.getLogger(__name__)
router = Router(name="korgan-reply-main-menu")


class ContractDetailsFilter(BaseFilter):
    async def __call__(self, message: Message, state: FSMContext) -> bool:
        data = await state.get_data()
        return data.get("mode") == "contract_details" and bool(message.text) and not message.text.startswith("/")


class ClaimRequestFilter(BaseFilter):
    """Recognize claim drafting unless the user explicitly entered consultation/contract mode."""

    async def __call__(self, message: Message, state: FSMContext) -> bool:
        data = await state.get_data()
        if data.get("mode") in {"consultation", "contract_details"}:
            return False
        return is_claim_drafting_request(message.text)


class ContractRequestFilter(BaseFilter):
    """Recognize contract drafting without stealing «иск по договору ...» from the claim router."""

    async def __call__(self, message: Message, state: FSMContext) -> bool:
        data = await state.get_data()
        if data.get("mode") == "consultation":
            return False
        if is_claim_drafting_request(message.text):
            return False
        return is_contract_drafting_request(message.text)


async def _save_user_text_as_facts(message: Message, state: FSMContext, *, min_length: int = 24) -> None:
    text = (message.text or "").strip()
    if not text or text in {"📄 Документ", "⚖️ Исковое заявление", "🤝 Договор"} or len(text) < min_length:
        return
    data = await state.get_data()
    facts = list(data.get("facts", []) or [])
    if text not in facts[-3:]:
        facts.append(text)
    await state.update_data(facts=facts[-20:])


async def _send_claim_as_word(message: Message, state: FSMContext) -> None:
    """A claim request must end in DOCX and the user's requested claim type must enter case context."""
    await _save_user_text_as_facts(message, state)
    context = await base_bot._case_context(state)

    if not context.strip():
        await message.answer(
            "⚖️ Сначала опишите обстоятельства дела или пришлите документы/сканы. Затем напишите, какой результат нужен, например: «подготовь иск о взыскании долга».",
            reply_markup=main_menu(),
        )
        return

    await state.update_data(mode="main")
    await base_bot.claim_handler(message, state)


async def _send_contract_as_word(message: Message, state: FSMContext) -> None:
    await _save_user_text_as_facts(message, state)
    context = await base_bot._case_context(state)

    if not context.strip() or len(context.strip()) < 80:
        await state.update_data(mode="contract_details")
        await message.answer(
            "🤝 Опишите договор одним сообщением:\n"
            "• какой договор нужен;\n"
            "• кто стороны и их роли;\n"
            "• предмет договора;\n"
            "• цена/оплата, если есть;\n"
            "• срок;\n"
            "• важные особые условия.\n\n"
            "Можно также прикрепить документы или переписку. KORGAN сам определит точный вид договора и проверит применимые нормы РК.",
            reply_markup=main_menu(),
        )
        return

    service = base_bot.service
    research_contract = getattr(service, "research_contract", None) if service is not None else None
    draft_contract = getattr(service, "draft_contract", None) if service is not None else None
    if research_contract is None or draft_contract is None:
        await message.answer("Функция договоров ещё не загружена в текущую версию сервиса.", reply_markup=main_menu())
        return

    await state.update_data(mode="main")
    data = await state.get_data()
    lang = str(data.get("language", "ru"))
    await message.answer("Проверяю вид договора и актуальные нормы РК, затем формирую Word-документ…")
    await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        research = await research_contract(context, language=lang)
        draft = await draft_contract(context, research, language=lang)
        file_bytes = build_contract_docx(draft)
    except Exception:
        LOGGER.exception("Contract generation failed")
        await message.answer(
            "Не удалось безопасно сформировать договор. KORGAN не будет выдавать юридически неподтверждённый текст. Проверьте исходные условия и повторите запрос.",
            reply_markup=main_menu(),
        )
        return

    marker = "✅ VERIFIED" if draft.status == VerificationStatus.VERIFIED else "⚠️ NEEDS_VERIFICATION"
    caption = f"{marker}\nПроект договора сформирован в Word (.docx)."
    if draft.verification_notes:
        notes = "\n".join(f"• {x}" for x in draft.verification_notes[:8])
        caption += f"\n\nПеред подписанием проверьте:\n{notes[:700]}"

    await message.answer_document(
        BufferedInputFile(file_bytes, filename="KORGAN_dogovor.docx"),
        caption=caption[:1000],
        reply_markup=main_menu(),
    )


@router.message(ContractDetailsFilter())
async def contract_details_reply(message: Message, state: FSMContext) -> None:
    await _save_user_text_as_facts(message, state, min_length=1)
    await state.update_data(mode="main")
    await _send_contract_as_word(message, state)


@router.message(ClaimRequestFilter())
async def natural_language_claim_request(message: Message, state: FSMContext) -> None:
    await _send_claim_as_word(message, state)


@router.message(ContractRequestFilter())
async def natural_language_contract_request(message: Message, state: FSMContext) -> None:
    await _send_contract_as_word(message, state)


@router.message(F.text == "📄 Документ")
async def document_button(message: Message, state: FSMContext) -> None:
    await state.update_data(mode="main")
    await message.answer(
        "📄 Что нужно подготовить?\n\nKORGAN сам определит точный вид иска или договора по вашим фактам и проверит актуальное право РК.",
        reply_markup=documents_menu(),
    )


@router.callback_query(F.data == "doc:claim")
async def document_claim_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is not None:
        await _send_claim_as_word(callback.message, state)


@router.callback_query(F.data == "doc:contract")
async def document_contract_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is not None:
        await _send_contract_as_word(callback.message, state)


@router.callback_query(F.data == "menu:main")
async def document_back_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.update_data(mode="main")
    if callback.message is not None:
        await callback.message.answer("🏠 Главное меню", reply_markup=main_menu())


@router.message(F.text == "⚖️ Консультация")
async def consultation_button(message: Message, state: FSMContext) -> None:
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
        f"📦 Моё дело\n\nДокументов / сканов: {len(docs)}\nТекстовых описаний: {len(facts)}.\n\n"
        "Добавляйте файлы, фото или текст. Затем нажмите «📄 Документ» и выберите иск или договор — либо напишите запрос обычным сообщением.",
        reply_markup=main_menu(),
    )


@router.message(F.text == "💰 Цены")
async def prices_button(message: Message, state: FSMContext) -> None:
    await state.update_data(mode="main")
    await message.answer(
        "💰 Акционные цены KORGAN\n\n"
        "🔥 Любой юридический документ — 1 000 ₸\n\n"
        "• Исковое заявление — 1 000 ₸\n"
        "• Жалоба — 1 000 ₸\n"
        "• Договор — 1 000 ₸\n"
        "• Отзыв на иск — 1 000 ₸\n"
        "• Досудебная претензия — 1 000 ₸\n\n"
        "🧪 Пока мы проверяем генерацию документов, оплата временно отключена. "
        "1 000 ₸ — текущая акционная цена для клиентов, а не постоянный тариф.",
        reply_markup=main_menu(),
    )


@router.message(F.text == "👨‍⚖️ Ваш персональный юрист")
async def lawyer_button(message: Message, state: FSMContext) -> None:
    await state.update_data(mode="main")
    await message.answer("👨‍⚖️ Раздел подключения живого юриста будет доступен после запуска клиентского режима.", reply_markup=main_menu())


@router.message(F.text == "❓ Помощь и частые вопросы")
async def help_button(message: Message, state: FSMContext) -> None:
    await state.update_data(mode="main")
    await message.answer(
        "❓ Как работать с KORGAN:\n"
        "1. Опишите ситуацию и при необходимости прикрепите материалы.\n"
        "2. Для иска напишите, например, «подготовь иск о взыскании долга». KORGAN определит тип требования и проверит профильные нормы.\n"
        "3. Для договора напишите, например, «составь договор оказания услуг…» либо выберите «📄 Документ» → «🤝 Договор».\n"
        "4. Документ придёт файлом Word (.docx).\n"
        "5. Неподтверждённые или отсутствующие данные отмечаются как NEEDS_VERIFICATION, а не придумываются.\n\n"
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
