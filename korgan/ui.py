from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)


def main_menu() -> ReplyKeyboardMarkup:
    """Persistent Telegram keyboard like the original KORGAN interface."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="⚖️ Консультация"),
                KeyboardButton(text="📄 Документ"),
            ],
            [
                KeyboardButton(text="💰 Цены"),
                KeyboardButton(text="📦 Моё дело"),
            ],
            [KeyboardButton(text="👨‍⚖️ Ваш персональный юрист")],
            [KeyboardButton(text="❓ Помощь и частые вопросы")],
            [KeyboardButton(text="🆘 Техподдержка")],
            [KeyboardButton(text="⭐ Оставить отзыв")],
            [KeyboardButton(text="🗑 Удалить мои данные")],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Выберите действие или напишите сообщение…",
    )


def documents_menu() -> InlineKeyboardMarkup:
    """Only real document-generation workflows; no generic «case analysis» item."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚖️ Исковое заявление", callback_data="doc:claim")],
            [InlineKeyboardButton(text="🤝 Договор", callback_data="doc:contract")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main")],
        ]
    )


def case_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📎 Добавить документ / скан", callback_data="doc:upload")],
            [InlineKeyboardButton(text="🧹 Очистить дело", callback_data="doc:clear")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main")],
        ]
    )


def back_to_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main")]
        ]
    )


def help_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚖️ Что умеет KORGAN", callback_data="help:capabilities")],
            [InlineKeyboardButton(text="📎 Как загрузить документ", callback_data="help:upload")],
            [InlineKeyboardButton(text="❗ Документ получился неполным", callback_data="help:incomplete")],
            [InlineKeyboardButton(text="🔐 Персональные данные", callback_data="help:privacy")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main")],
        ]
    )


def delete_confirm_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, удалить данные дела", callback_data="delete:confirm")],
            [InlineKeyboardButton(text="↩️ Отмена", callback_data="menu:main")],
        ]
    )


WELCOME_TEXT = (
    "⚖️ <b>KORGAN Legal AI</b>\n\n"
    "Юридический AI‑ассистент по законодательству Республики Казахстан.\n\n"
    "Можно получить консультацию, загрузить PDF/DOCX/TXT, фото или скан, "
    "подготовить исковое заявление или профессиональный договор.\n\n"
    "🔎 Точные нормы, сроки, госпошлина и подсудность используются только после "
    "проверки официальных источников. Если подтверждения недостаточно — KORGAN "
    "покажет <b>NEEDS_VERIFICATION</b>, а не будет угадывать.\n\n"
    "Выберите нужный раздел 👇"
)

MAIN_TEXT = "🏠 <b>Главное меню</b>\n\nВыберите нужный раздел 👇"

DOCUMENTS_TEXT = (
    "📄 <b>Документ</b>\n\n"
    "Выберите: исковое заявление или договор. Готовый документ придёт отдельным файлом .docx."
)
