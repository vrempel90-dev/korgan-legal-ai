from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from korgan.i18n import KK, RU, button, normalize_language, tr


def main_menu(language: str = RU) -> ReplyKeyboardMarkup:
    """Persistent Telegram keyboard in the selected client language."""
    lang = normalize_language(language)
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=button(lang, "consultation")),
                KeyboardButton(text=button(lang, "document")),
            ],
            [
                KeyboardButton(text=button(lang, "prices")),
                KeyboardButton(text=button(lang, "case")),
            ],
            [KeyboardButton(text=button(lang, "lawyer"))],
            [KeyboardButton(text=button(lang, "help"))],
            [KeyboardButton(text=button(lang, "support"))],
            [KeyboardButton(text=button(lang, "feedback"))],
            [KeyboardButton(text=button(lang, "language"))],
            [KeyboardButton(text=button(lang, "delete"))],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder=(
            "Әрекетті таңдаңыз немесе хабарлама жазыңыз…"
            if lang == KK
            else "Выберите действие или напишите сообщение…"
        ),
    )


def language_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🇰🇿 Қазақша", callback_data="lang:kk")],
            [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru")],
        ]
    )


def documents_menu(language: str = RU) -> InlineKeyboardMarkup:
    lang = normalize_language(language)
    pretrial = "📨 Сотқа дейінгі талап" if lang == KK else "📨 Досудебная претензия"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=button(lang, "claim"), callback_data="doc:claim")],
            [InlineKeyboardButton(text=pretrial, callback_data="doc:pretrial")],
            [InlineKeyboardButton(text=button(lang, "response"), callback_data="doc:response")],
            [InlineKeyboardButton(text=button(lang, "contract"), callback_data="doc:contract")],
            [InlineKeyboardButton(text=button(lang, "main"), callback_data="menu:main")],
        ]
    )


def case_menu(language: str = RU) -> InlineKeyboardMarkup:
    lang = normalize_language(language)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=button(lang, "upload"), callback_data="doc:upload")],
            [InlineKeyboardButton(text=button(lang, "clear"), callback_data="doc:clear")],
            [InlineKeyboardButton(text=button(lang, "main"), callback_data="menu:main")],
        ]
    )


def back_to_main(language: str = RU) -> InlineKeyboardMarkup:
    lang = normalize_language(language)
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=button(lang, "main"), callback_data="menu:main")]]
    )


def help_menu(language: str = RU) -> InlineKeyboardMarkup:
    lang = normalize_language(language)
    rows = (
        [
            ("⚖️ KORGAN не істей алады", "help:capabilities"),
            ("📎 Құжатты қалай жүктеуге болады", "help:upload"),
            ("❗ Құжат толық емес болып шықты", "help:incomplete"),
            ("🔐 Дербес деректер", "help:privacy"),
        ]
        if lang == KK
        else [
            ("⚖️ Что умеет KORGAN", "help:capabilities"),
            ("📎 Как загрузить документ", "help:upload"),
            ("❗ Документ получился неполным", "help:incomplete"),
            ("🔐 Персональные данные", "help:privacy"),
        ]
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            *[[InlineKeyboardButton(text=text, callback_data=data)] for text, data in rows],
            [InlineKeyboardButton(text=button(lang, "main"), callback_data="menu:main")],
        ]
    )


def delete_confirm_menu(language: str = RU) -> InlineKeyboardMarkup:
    lang = normalize_language(language)
    yes, cancel = (
        ("✅ Иә, іс деректерін жою", "↩️ Болдырмау")
        if lang == KK
        else ("✅ Да, удалить данные дела", "↩️ Отмена")
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=yes, callback_data="delete:confirm")],
            [InlineKeyboardButton(text=cancel, callback_data="menu:main")],
        ]
    )


# Backward-compatible Russian constants used by older modules.
WELCOME_TEXT = tr(RU, "welcome")
MAIN_TEXT = tr(RU, "main")
DOCUMENTS_TEXT = tr(RU, "documents")
