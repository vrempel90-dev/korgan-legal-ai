from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardRemove,
    TelegramObject,
)

from korgan import bot as base_bot
from korgan.ui import WELCOME_TEXT, main_menu

LOGGER = logging.getLogger(__name__)
router = Router(name="korgan-legal-safety")

TERMS_VERSION = "2026-08-16-v1"

TERMS_TEXT = (
    "🛡 <b>Условия использования KORGAN Legal AI</b>\n\n"
    "Перед использованием подтвердите условия.\n\n"
    "1. <b>KORGAN — система искусственного интеллекта.</b> Ответы и документы формируются автоматически на основании данных пользователя и найденных источников. KORGAN не является судом, государственным органом и не гарантирует принятие документа или исход дела.\n\n"
    "2. <b>Факты предоставляет пользователь.</b> Вы подтверждаете, что сообщаемые сведения и загружаемые документы являются достоверными настолько, насколько вам известно, и что у вас есть законные основания передавать содержащиеся в них персональные данные. KORGAN не должен создавать факты или доказательства, которых нет в материалах.\n\n"
    "3. <b>Правовые нормы проверяются.</b> Если статья, срок, госпошлина, подсудность или иной значимый вывод не подтвержден официальным источником, KORGAN должен отметить его как <b>NEEDS_VERIFICATION</b>. Такие пункты нельзя считать подтвержденными до дополнительной проверки.\n\n"
    "4. <b>Документы являются проектами.</b> Перед подачей в суд или государственный орган необходимо проверить Ф.И.О./ИИН, адреса, даты, суммы, доказательства, требования, подсудность, госпошлину и все отметки NEEDS_VERIFICATION. Для сложных или спорных дел рекомендуется проверка живым юристом/адвокатом.\n\n"
    "5. <b>Нет гарантии результата.</b> Итог зависит от доказательств, позиции другой стороны, процессуальных действий и решения суда/органа. В пределах, допускаемых законодательством РК, KORGAN не отвечает за последствия, вызванные недостоверными или неполными данными пользователя, изменением законодательства после подготовки документа, игнорированием предупреждений системы либо самостоятельными решениями суда/государственных органов. Это условие не ограничивает права пользователя, которые не могут быть ограничены законом.\n\n"
    "6. <b>Персональные данные.</b> Нажимая «Принимаю», вы даёте согласие на сбор и обработку переданных вами данных в объёме, необходимом для консультации, анализа материалов, формирования документов, обеспечения безопасности и подтверждения принятия условий. Данные текущего дела можно удалить через кнопку «🗑 Удалить мои данные».\n\n"
    "7. <b>Запрещено</b> использовать KORGAN для подделки доказательств, мошенничества, выдачи себя за другое лицо или иной незаконной деятельности.\n\n"
    f"Версия условий: <code>{TERMS_VERSION}</code>"
)

PRIVACY_TEXT = (
    "🔐 <b>Персональные данные и конфиденциальность</b>\n\n"
    "KORGAN обрабатывает только те сведения, которые пользователь сам отправляет в чат или прикрепляет к делу, а также технические идентификаторы, необходимые для работы Telegram-сессии и фиксации согласия.\n\n"
    "Цель обработки: юридическая консультация, извлечение фактов из материалов, формирование документов, безопасность сервиса и подтверждение принятия условий.\n\n"
    "В текущей тестовой архитектуре материалы дела хранятся в памяти процесса и могут быть удалены кнопкой «🗑 Удалить мои данные» либо исчезнуть при перезапуске сервиса. Для промышленной версии журнал согласий и данные дела должны храниться в постоянном защищённом хранилище с установленным сроком хранения."
)

CLAIM_CONFIRM_TEXT = (
    "⚠️ <b>Перед формированием судебного документа</b>\n\n"
    "Подтвердите, что:\n"
    "• вы проверите персональные данные и факты;\n"
    "• не будете считать пункты NEEDS_VERIFICATION подтверждёнными;\n"
    "• понимаете, что документ является проектом и не гарантирует исход дела;\n"
    "• понимаете, что решение о подаче документа принимаете вы.\n\n"
    "После подтверждения KORGAN проверит правовую основу и сформирует файл .docx."
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def terms_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принимаю условия", callback_data="terms:accept")],
            [InlineKeyboardButton(text="🔐 Конфиденциальность", callback_data="terms:privacy")],
            [InlineKeyboardButton(text="❌ Не принимаю", callback_data="terms:decline")],
        ]
    )


def claim_confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Согласен, сформировать документ", callback_data="claim:confirm")],
            [InlineKeyboardButton(text="↩️ Отмена", callback_data="claim:cancel")],
        ]
    )


async def has_current_consent(state: FSMContext | None) -> bool:
    if state is None:
        return False
    data = await state.get_data()
    return bool(data.get("terms_accepted")) and data.get("terms_version") == TERMS_VERSION


async def show_terms(message: Message) -> None:
    await message.answer(
        TERMS_TEXT,
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )
    await message.answer(
        "Чтобы продолжить работу с KORGAN, выберите действие:",
        reply_markup=terms_keyboard(),
    )


class ConsentMiddleware(BaseMiddleware):
    """Fail closed: no legal processing before the current terms are accepted."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)

        text = (event.text or "").strip()
        if text.startswith("/start") or text.startswith("/terms") or text.startswith("/privacy"):
            return await handler(event, data)

        state = data.get("state")
        if await has_current_consent(state):
            return await handler(event, data)

        await show_terms(event)
        return None


@router.callback_query(F.data == "terms:accept")
async def accept_terms(callback: CallbackQuery, state: FSMContext) -> None:
    accepted_at = utc_now_iso()
    data = await state.get_data()
    await state.update_data(
        language=str(data.get("language", "ru")),
        documents=list(data.get("documents", []) or []),
        facts=list(data.get("facts", []) or []),
        terms_accepted=True,
        terms_version=TERMS_VERSION,
        terms_accepted_at=accepted_at,
        privacy_consent=True,
    )
    LOGGER.info(
        "LEGAL_TERMS_ACCEPTED version=%s telegram_user_id=%s accepted_at=%s",
        TERMS_VERSION,
        callback.from_user.id,
        accepted_at,
    )
    await callback.answer("Условия приняты")
    chat_id = getattr(getattr(callback.message, "chat", None), "id", callback.from_user.id)
    await callback.bot.send_message(
        chat_id,
        "✅ Условия приняты.\n\n" + WELCOME_TEXT,
        parse_mode="HTML",
        reply_markup=main_menu(),
    )


@router.callback_query(F.data == "terms:privacy")
async def privacy_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    chat_id = getattr(getattr(callback.message, "chat", None), "id", callback.from_user.id)
    await callback.bot.send_message(chat_id, PRIVACY_TEXT, parse_mode="HTML", reply_markup=terms_keyboard())


@router.callback_query(F.data == "terms:decline")
async def decline_terms(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_data({"language": "ru", "documents": [], "facts": [], "terms_accepted": False})
    LOGGER.info("LEGAL_TERMS_DECLINED version=%s telegram_user_id=%s", TERMS_VERSION, callback.from_user.id)
    await callback.answer("Условия не приняты")
    chat_id = getattr(getattr(callback.message, "chat", None), "id", callback.from_user.id)
    await callback.bot.send_message(
        chat_id,
        "Без принятия условий KORGAN не будет обрабатывать юридические запросы и документы. Вы можете вернуться к /start в любое время.",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.callback_query(F.data == "claim:cancel")
async def cancel_claim(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(claim_confirmation_pending=False)
    await callback.answer("Формирование отменено")
    chat_id = getattr(getattr(callback.message, "chat", None), "id", callback.from_user.id)
    await callback.bot.send_message(chat_id, "Формирование документа отменено.", reply_markup=main_menu())


@router.callback_query(F.data == "claim:confirm")
async def confirm_claim(callback: CallbackQuery, state: FSMContext) -> None:
    if not await has_current_consent(state):
        await callback.answer("Сначала примите условия", show_alert=True)
        chat_id = getattr(getattr(callback.message, "chat", None), "id", callback.from_user.id)
        await callback.bot.send_message(chat_id, TERMS_TEXT, parse_mode="HTML", reply_markup=terms_keyboard())
        return

    data = await state.get_data()
    if not data.get("claim_confirmation_pending"):
        await callback.answer("Подтверждение устарело", show_alert=True)
        return

    confirmed_at = utc_now_iso()
    await state.update_data(
        claim_confirmation_pending=False,
        claim_warning_confirmed_at=confirmed_at,
        claim_warning_version=TERMS_VERSION,
    )
    LOGGER.info(
        "CLAIM_DRAFT_WARNING_ACCEPTED version=%s telegram_user_id=%s accepted_at=%s",
        TERMS_VERSION,
        callback.from_user.id,
        confirmed_at,
    )
    await callback.answer("Начинаю формирование")

    message = callback.message
    chat_id = getattr(getattr(message, "chat", None), "id", callback.from_user.id)
    if message is None:
        await callback.bot.send_message(chat_id, "Не удалось запустить формирование. Отправьте /menu и повторите.", reply_markup=main_menu())
        return

    try:
        await base_bot.claim_handler(message, state)  # type: ignore[arg-type]
    except Exception:
        LOGGER.exception("Confirmed claim generation failed")
        await callback.bot.send_message(
            chat_id,
            "Не удалось сформировать документ. Материалы дела сохранены; повторите попытку позже.",
            reply_markup=main_menu(),
        )
