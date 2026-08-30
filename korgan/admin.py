from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from korgan.admin_report import send_admin_report
from korgan.config import Settings, get_settings
from korgan.miniapp_document_payments import decide_document_order, get_document_order

LOGGER = logging.getLogger(__name__)
router = Router(name="admin")


def is_admin(user_id: int | None, settings: Settings | None = None) -> bool:
    """Fail closed: absent/unknown users never receive administrator access."""
    if user_id is None:
        return False
    current_settings = settings or get_settings()
    try:
        return user_id in current_settings.admin_ids
    except (TypeError, ValueError):
        LOGGER.exception("Invalid ADMIN_TELEGRAM_IDS configuration")
        return False


def _button(text: str, action: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=f"admin:{action}")


def admin_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("👥 Пользователи", "users"), _button("💬 Консультации", "consultations")],
            [_button("📄 Документы", "documents"), _button("⚖️ Обращения", "lawyer_requests")],
            [_button("📚 Legal RAG", "rag"), _button("🚨 Контроль", "quality")],
            [_button("📊 Аналитика", "analytics"), _button("📨 Отчёт", "report")],
            [_button("💰 Расходы", "costs"), _button("⚙️ Настройки", "settings")],
            [_button("🔐 Безопасность", "security")],
            [_button("🔄 Обновить", "home"), _button("✖️ Закрыть", "close")],
        ]
    )


def admin_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("⬅️ Админ-меню", "home"), _button("✖️ Закрыть", "close")],
        ]
    )


def _configured(value: str) -> str:
    return "🟢 настроено" if bool(value.strip()) else "🔴 не настроено"


def admin_home_text(settings: Settings) -> str:
    return (
        "🛡 KORGAN — АДМИН-ПАНЕЛЬ\n\n"
        "Доступ: 🔒 только ADMIN_TELEGRAM_IDS\n"
        "Telegram: 🟢 admin-only\n"
        f"OpenAI для пользовательского Telegram-бота: 🔴 отключён\n"
        f"Отчёты: {'🟢 настроены' if settings.admin_report_id is not None else '🔴 не настроены'}\n"
        "Проверка оплат: 🟢 прямо в Telegram\n\n"
        "Выберите раздел:"
    )


def admin_page(action: str, settings: Settings) -> tuple[str, InlineKeyboardMarkup]:
    domains = ", ".join(settings.legal_domains) or "не настроены"
    pages: dict[str, str] = {
        "users": (
            "👥 ПОЛЬЗОВАТЕЛИ\n\n"
            "Постоянный реестр пользователей сейчас не подключён. "
            "Текущая версия использует MemoryStorage, поэтому админка не показывает выдуманную статистику.\n\n"
            "Следующий безопасный шаг: подключить PostgreSQL-реестр с псевдонимизированными Telegram ID."
        ),
        "consultations": (
            "💬 КОНСУЛЬТАЦИИ\n\n"
            "Пользовательский Telegram AI-агент отключён. MiniApp продолжает обслуживать подготовку документов."
        ),
        "documents": (
            "📄 ДОКУМЕНТЫ\n\n"
            "Генерация документов работает в MiniApp. Чеки по оплате документов приходят сюда отдельным сообщением с кнопками «Подтвердить» и «Отклонить»."
        ),
        "lawyer_requests": (
            "⚖️ ОБРАЩЕНИЯ К ЮРИСТУ\n\n"
            "Клиентские обращения направляются персональному юристу через настроенный канал связи."
        ),
        "rag": (
            "📚 LEGAL RAG\n\n"
            f"Официальные домены: {domains}\n"
            "Политика: точные нормы, сроки, госпошлина и подсудность не должны считаться подтверждёнными без официального источника.\n\n"
            "Fail-closed нельзя отключить из Telegram-админки."
        ),
        "quality": (
            "🚨 КОНТРОЛЬ КАЧЕСТВА\n\n"
            "Внутренние quality-gates продолжают работать для документов MiniApp и не показываются клиенту."
        ),
        "analytics": (
            "📊 АНАЛИТИКА\n\n"
            "Доступна подтверждаемая дневная сводка из PostgreSQL. Нажмите «📨 Отчёт» в админ-меню, чтобы отправить её на отдельный Telegram ID получателя."
        ),
        "costs": (
            "💰 РАСХОДЫ\n\n"
            "Пользовательский Telegram AI-агент отключён. Расходы генерации документов MiniApp учитываются отдельно от этого admin-only бота."
        ),
        "settings": (
            "⚙️ НАСТРОЙКИ\n\n"
            f"Макс. документов в деле: {settings.max_case_documents}\n"
            f"Макс. текста дела: {settings.max_case_text_chars} символов\n"
            f"Официальные домены: {domains}\n"
            f"Администраторов настроено: {len(settings.admin_ids)}\n"
            f"Получатель отчётов: {'настроен' if settings.admin_report_id is not None else 'не настроен'}\n"
            f"Автоотчёт: {settings.admin_report_hour_almaty:02d}:00 по Алматы\n\n"
            "Секреты и критические политики изменяются только через защищённые переменные окружения Railway."
        ),
        "security": (
            "🔐 БЕЗОПАСНОСТЬ\n\n"
            "• Вход только по Telegram user ID из ADMIN_TELEGRAM_IDS.\n"
            "• Каждая кнопка подтверждения оплаты повторно проверяет права администратора.\n"
            "• Решение оплаты записывается атомарно в PostgreSQL.\n"
            "• Повторное нажатие не проводит оплату повторно.\n"
            "• API-ключи никогда не выводятся в чат."
        ),
    }
    return pages.get(action, "Раздел не найден."), admin_back_keyboard()


async def _deny_message(message: Message) -> None:
    user_id = message.from_user.id if message.from_user else None
    LOGGER.warning("ADMIN_ACCESS_DENIED telegram_user_id=%s", user_id)
    await message.answer("Команда недоступна.")


async def _show_admin(message: Message) -> None:
    user_id = message.from_user.id if message.from_user else None
    settings = get_settings()
    if not is_admin(user_id, settings):
        await _deny_message(message)
        return
    LOGGER.info("ADMIN_ACCESS_GRANTED telegram_user_id=%s", user_id)
    await message.answer(admin_home_text(settings), reply_markup=admin_main_keyboard())


@router.message(CommandStart())
async def admin_start(message: Message) -> None:
    await _show_admin(message)


@router.message(Command("admin"))
async def admin_command(message: Message) -> None:
    await _show_admin(message)


@router.callback_query(F.data.startswith("adminpay:"))
async def admin_payment_callback(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else None
    settings = get_settings()
    if not is_admin(user_id, settings):
        LOGGER.warning("ADMIN_PAYMENT_DENIED telegram_user_id=%s data=%s", user_id, callback.data)
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    parts = str(callback.data or "").split(":")
    if len(parts) != 3 or parts[1] not in {"approve", "reject"}:
        await callback.answer("Некорректная команда.", show_alert=True)
        return
    try:
        order_id = int(parts[2])
    except ValueError:
        await callback.answer("Некорректный номер заказа.", show_alert=True)
        return

    order = await get_document_order(order_id)
    if order is None:
        await callback.answer("Заказ не найден.", show_alert=True)
        return

    approved = parts[1] == "approve"
    if order.status != "awaiting_admin":
        if approved and order.status in {"approved", "consumed"}:
            await callback.answer("Оплата уже подтверждена.")
        elif not approved and order.status == "pending_receipt":
            await callback.answer("Чек уже отклонён; ожидается новый чек.")
        else:
            await callback.answer(f"Заказ уже имеет статус: {order.status}.", show_alert=True)
        return

    decision = "approved" if approved else "rejected"
    changed = await decide_document_order(
        order_id,
        approved=approved,
        note=f"telegram admin {user_id}: {decision}",
    )
    latest = await get_document_order(order_id)
    if not changed or latest is None:
        await callback.answer("Статус уже изменён другим действием. Обновите сообщение.", show_alert=True)
        return

    if approved:
        status_text = "✅ ОПЛАТА ПОДТВЕРЖДЕНА"
        answer_text = "Оплата подтверждена. Клиент может продолжить подготовку документа."
    else:
        status_text = "❌ ЧЕК ОТКЛОНЁН"
        answer_text = "Чек отклонён. Клиент сможет загрузить другой чек без создания нового заказа."

    LOGGER.info(
        "ADMIN_PAYMENT_DECISION telegram_user_id=%s order_id=%s decision=%s status=%s",
        user_id,
        order_id,
        decision,
        latest.status,
    )
    await callback.answer(answer_text)
    if callback.message:
        old_caption = (callback.message.caption or "").strip()
        suffix = f"\n\n{status_text}\nАдминистратор: {user_id}"
        try:
            await callback.message.edit_caption(
                caption=(old_caption + suffix)[:1024],
                reply_markup=None,
            )
        except Exception:
            LOGGER.exception("ADMIN_PAYMENT_MESSAGE_EDIT_FAILED order_id=%s", order_id)


@router.callback_query(F.data.startswith("admin:"))
async def admin_callback(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else None
    settings = get_settings()
    if not is_admin(user_id, settings):
        LOGGER.warning("ADMIN_CALLBACK_DENIED telegram_user_id=%s action=%s", user_id, callback.data)
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    action = (callback.data or "admin:home").split(":", 1)[1]
    if action == "close":
        await callback.answer()
        if callback.message:
            await callback.message.delete()
        return

    if action == "report":
        if settings.admin_report_id is None:
            await callback.answer("Получатель отчёта не настроен.", show_alert=True)
            return
        try:
            sent = await send_admin_report(callback.bot, settings)
        except Exception:
            LOGGER.exception("ADMIN_REPORT_MANUAL_SEND_FAILED requested_by=%s", user_id)
            await callback.answer("Не удалось отправить отчёт. Проверьте Telegram ID и доступ бота к чату.", show_alert=True)
            return
        if not sent:
            await callback.answer("Получатель отчёта не настроен.", show_alert=True)
            return
        await callback.answer("Отчёт отправлен.")
        if callback.message:
            await callback.message.edit_text(
                "📨 ОТЧЁТ\n\nДневная сводка отправлена на настроенный Telegram ID получателя.",
                reply_markup=admin_back_keyboard(),
            )
        return

    if action == "home":
        text = admin_home_text(settings)
        keyboard = admin_main_keyboard()
    else:
        text, keyboard = admin_page(action, settings)

    await callback.answer()
    if callback.message:
        await callback.message.edit_text(text, reply_markup=keyboard()) if callable(keyboard) else await callback.message.edit_text(text, reply_markup=keyboard)
