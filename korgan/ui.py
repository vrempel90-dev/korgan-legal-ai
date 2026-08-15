from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⚖️ Консультация", callback_data="menu:consult"),
                InlineKeyboardButton(text="📄 Документы", callback_data="menu:documents"),
            ],
            [
                InlineKeyboardButton(text="💰 Цены", callback_data="menu:prices"),
                InlineKeyboardButton(text="📦 Моё дело", callback_data="menu:case"),
            ],
            [InlineKeyboardButton(text="👨‍⚖️ Ваш персональный юрист", callback_data="menu:lawyer")],
            [InlineKeyboardButton(text="❓ Помощь и частые вопросы", callback_data="menu:help")],
            [InlineKeyboardButton(text="🆘 Техподдержка", callback_data="menu:support")],
            [InlineKeyboardButton(text="⭐ Оставить отзыв", callback_data="menu:feedback")],
            [InlineKeyboardButton(text="🗑 Удалить мои данные", callback_data="menu:delete")],
        ]
    )


def documents_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📄 Исковое заявление — Word", callback_data="doc:claim")],
            [InlineKeyboardButton(text="📎 Загрузить документы / сканы", callback_data="doc:upload")],
            [InlineKeyboardButton(text="📂 Материалы текущего дела", callback_data="doc:case")],
            [InlineKeyboardButton(text="🧹 Очистить текущее дело", callback_data="doc:clear")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main")],
        ]
    )


def case_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📎 Добавить документ / скан", callback_data="doc:upload")],
            [InlineKeyboardButton(text="📄 Подготовить иск в Word", callback_data="doc:claim")],
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
            [InlineKeyboardButton(text="📄 Как подготовить иск", callback_data="help:claim")],
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
    "извлечь необходимые факты из документов и подготовить проект искового заявления в формате Word (.docx).\n\n"
    "🔎 Точные нормы, сроки, госпошлина и подсудность используются только после "
    "проверки официальных источников. Если подтверждения недостаточно — KORGAN "
    "покажет <b>NEEDS_VERIFICATION</b>, а не будет угадывать.\n\n"
    "Выберите нужный раздел 👇"
)

MAIN_TEXT = "🏠 <b>Главное меню</b>\n\nВыберите нужный раздел 👇"

DOCUMENTS_TEXT = (
    "📄 <b>Работа с документами</b>\n\n"
    "Загрузите материалы дела или подготовьте иск. Готовое исковое заявление KORGAN отправит отдельным файлом Word (.docx)."
)
