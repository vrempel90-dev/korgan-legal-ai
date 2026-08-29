from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from korgan.admin_report import send_admin_report
from korgan.config import Settings, get_settings

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
            [_button("📚 Legal RAG", "rag"), _button("🤖 AI", "ai")],
            [_button("🚨 Контроль", "quality"), _button("📊 Аналитика", "analytics")],
            [_button("📨 Отчёт", "report"), _button("💰 Расходы", "costs")],
            [_button("⚙️ Настройки", "settings"), _button("🔐 Безопасность", "security")],
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
        "🛡 KORGAN AI — АДМИН-ПАНЕЛЬ\n\n"
        "Доступ: 🔒 только ADMIN_TELEGRAM_IDS\n"
        "Telegram: 🟢 бот работает\n"
        f"OpenAI: {_configured(settings.openai_api_key)}\n"
        f"Модель: {settings.openai_model}\n"
        f"Отчёты: {'🟢 настроены' if settings.admin_report_id is not None else '🔴 не настроены'}\n"
        "Fail-closed: 🔒 не изменяется из админки\n\n"
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
            "Просмотр полной истории консультаций не включён. Дневной отчёт использует только реальные агрегаты из PostgreSQL: использование квоты и оплаченные консультации."
        ),
        "documents": (
            "📄 ДОКУМЕНТЫ\n\n"
            "Генерация работает в основном контуре KORGAN. Дневной отчёт считает только подтверждённые Kaspi ОФД оплаты Agent и завершённые оплаченные документы Mini App."
        ),
        "lawyer_requests": (
            "⚖️ ОБРАЩЕНИЯ К ЮРИСТУ\n\n"
            "Очередь живого юриста пока не подключена к постоянной базе.\n\n"
            "После подключения: новые → в работе → завершённые → просроченные, с назначением ответственного юриста."
        ),
        "rag": (
            "📚 LEGAL RAG\n\n"
            f"Официальные домены: {domains}\n"
            "Политика: точные нормы, сроки, госпошлина и подсудность не должны считаться подтверждёнными без официального источника.\n\n"
            "Fail-closed нельзя отключить из Telegram-админки."
        ),
        "ai": (
            "🤖 УПРАВЛЕНИЕ AI\n\n"
            f"Консультации: {settings.openai_model}\n"
            f"Vision: {settings.openai_vision_model}\n"
            f"Validation: {settings.openai_validation_model}\n"
            f"OpenAI API key: {_configured(settings.openai_api_key)}\n\n"
            "API-ключи и системные секреты в Telegram не отображаются и не редактируются."
        ),
        "quality": (
            "🚨 КОНТРОЛЬ КАЧЕСТВА\n\n"
            "Fail-closed: 🔒 включён архитектурно.\n"
            "NEEDS_VERIFICATION должен блокировать уверенную выдачу неподтверждённых юридических реквизитов.\n\n"
            "Счётчики ошибок появятся после подключения постоянного журнала событий."
        ),
        "analytics": (
            "📊 АНАЛИТИКА\n\n"
            "Доступна подтверждаемая дневная сводка из PostgreSQL. Нажмите «📨 Отчёт» в админ-меню, чтобы отправить её на отдельный Telegram ID получателя.\n\n"
            "Полная продуктовая аналитика, графики и экспорт остаются отдельным этапом."
        ),
        "costs": (
            "💰 РАСХОДЫ AI\n\n"
            "Учёт токенов и стоимости по запросам пока не записывается в постоянное хранилище.\n\n"
            "В следующей версии можно добавить расход по консультациям, документам, vision и валидации без раскрытия API-ключей."
        ),
        "settings": (
            "⚙️ НАСТРОЙКИ\n\n"
            f"Макс. документов в деле: {settings.max_case_documents}\n"
            f"Макс. текста дела: {settings.max_case_text_chars} символов\n"
            f"Официальные домены: {domains}\n"
            f"Администраторов настроено: {len(settings.admin_ids)}\n"
            f"Получатель отчётов: {'настроен' if settings.admin_report_id is not None else 'не настроен'}\n"
            f"Автоотчёт: {settings.admin_report_hour_almaty:02d}:00 по Алматы\n\n"
            "ADMIN_REPORT_TELEGRAM_ID не предоставляет доступ к /admin. Секреты и критические политики изменяются только через защищённые переменные окружения Railway."
        ),
        "security": (
            "🔐 БЕЗОПАСНОСТЬ\n\n"
            "• Вход только по Telegram user ID из ADMIN_TELEGRAM_IDS.\n"
            "• ADMIN_REPORT_TELEGRAM_ID — только адрес доставки отчёта и не даёт прав администратора.\n"
            "• Проверка выполняется и для /admin, и для каждого callback.\n"
            "• При пустом/ошибочном списке доступ закрывается для всех (fail-closed).\n"
            "• API-ключи никогда не выводятся в чат.\n"
            "• Fail-closed юридического контура из админки не отключается."
        ),
    }
    return pages.get(action, "Раздел не найден."), admin_back_keyboard()


async def _deny_message(message: Message) -> None:
    user_id = message.from_user.id if message.from_user else None
    LOGGER.warning("ADMIN_ACCESS_DENIED telegram_user_id=%s", user_id)
    await message.answer("Команда недоступна.")


@router.message(Command("admin"))
async def admin_command(message: Message) -> None:
    user_id = message.from_user.id if message.from_user else None
    settings = get_settings()
    if not is_admin(user_id, settings):
        await _deny_message(message)
        return

    LOGGER.info("ADMIN_ACCESS_GRANTED telegram_user_id=%s", user_id)
    await message.answer(admin_home_text(settings), reply_markup=admin_main_keyboard())


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
        await callback.message.edit_text(text, reply_markup=keyboard)
