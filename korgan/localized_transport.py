from __future__ import annotations

from typing import Any

from aiogram import Bot
from aiogram.methods import SendDocument
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from korgan.client_safe_ui import ClientSafeBot, _clean_upload, sanitize_client_text
from korgan.i18n import BUTTONS, KK, RU, tr
from korgan.language_context import current_language

_BUTTON_MAP = {value: BUTTONS[KK][key] for key, value in BUTTONS[RU].items()}
_REVIEW_PHONE = "77005000553"
_DOCUMENT_KINDS = {
    "korgan_iskovoe_zayavlenie.docx": "claim",
    "korgan_otzyv_na_isk.docx": "response",
    "korgan_dogovor.docx": "contract",
    "korgan_dosudebnaya_pretenziya.docx": "pretrial",
    "korgan_sotqa_deyingi_talap.docx": "pretrial",
    "korgan_otvet_na_pretenziyu.docx": "pretrial_response",
    "korgan_sotqa_deyingi_talapqa_zhauap.docx": "pretrial_response",
}


def _generated_document_kind(document: Any) -> str | None:
    filename = str(getattr(document, "filename", "") or "").rsplit("/", 1)[-1].lower()
    return _DOCUMENT_KINDS.get(filename)


def _document_client_caption(kind: str, language: str) -> str:
    if language == KK:
        return {
            "claim": "✅ Талап қою арызы Word (.docx) форматында дайын.",
            "pretrial": "✅ Сотқа дейінгі талап Word (.docx) форматында дайын.",
            "pretrial_response": "✅ Сотқа дейінгі талапқа жауап Word (.docx) форматында дайын.",
            "response": "✅ Талап қою арызына пікір Word (.docx) форматында дайын.",
            "contract": "✅ Шарт Word (.docx) форматында дайын.",
        }[kind]
    return {
        "claim": "✅ Иск сформирован в Word (.docx).",
        "pretrial": "✅ Досудебная претензия сформирована в Word (.docx).",
        "pretrial_response": "✅ Ответ на претензию сформирован в Word (.docx).",
        "response": "✅ Отзыв на иск сформирован в Word (.docx).",
        "contract": "✅ Договор сформирован в Word (.docx).",
    }[kind]


def _claim_client_caption(language: str) -> str:
    """Backward-compatible helper kept for existing tests/callers."""
    return _document_client_caption("claim", language)


def _document_review_text(kind: str, language: str) -> str:
    if language == KK:
        document = {
            "claim": "талап қою арызын",
            "pretrial": "сотқа дейінгі талапты",
            "pretrial_response": "сотқа дейінгі талапқа жауапты",
            "response": "пікірді",
            "contract": "шартты",
        }[kind]
        return (
            f"⚠️ {document.capitalize()} кәсіби заңгерге тексертуге кеңес береміз.\n"
            "Тексеру ақылы. Қосымша қызметтер ақылы.\n"
            "Заңгерге жіберу керек пе?"
        )

    document = {
        "claim": "иск",
        "pretrial": "досудебную претензию",
        "pretrial_response": "ответ на претензию",
        "response": "отзыв на иск",
        "contract": "договор",
    }[kind]
    return (
        f"⚠️ Рекомендуем проверить {document} у профессионального юриста.\n"
        "Проверка платная. Доп. услуги — платные.\n"
        "Передать юристу?"
    )


def _document_caption_with_review(kind: str, language: str) -> str:
    return f"{_document_client_caption(kind, language)}\n\n{_document_review_text(kind, language)}"


def _document_review_markup(kind: str, language: str) -> InlineKeyboardMarkup:
    if language == KK:
        yes_label = "✅ Иә"
        no_label = "❌ Жоқ"
    else:
        yes_label = "✅ Да"
        no_label = "❌ Нет"

    # Keep the destination short and readable in Telegram's external-link dialog.
    # Document type and paid-service terms remain visible in the compact CTA.
    url = f"https://wa.me/{_REVIEW_PHONE}"
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text=yes_label, url=url),
            InlineKeyboardButton(text=no_label, callback_data=f"lawyer_review:{kind}:no"),
        ]]
    )


def _localize_markup(markup: Any) -> Any:
    if current_language() != KK or markup is None:
        return markup

    if isinstance(markup, ReplyKeyboardMarkup):
        rows: list[list[KeyboardButton]] = []
        for row in markup.keyboard:
            rows.append([
                button.model_copy(update={"text": _BUTTON_MAP.get(button.text, button.text)})
                for button in row
            ])
        return markup.model_copy(
            update={
                "keyboard": rows,
                "input_field_placeholder": "Әрекетті таңдаңыз немесе хабарлама жазыңыз…",
            }
        )

    if isinstance(markup, InlineKeyboardMarkup):
        rows = []
        for row in markup.inline_keyboard:
            rows.append([
                button.model_copy(update={"text": _BUTTON_MAP.get(button.text, button.text)})
                for button in row
            ])
        return markup.model_copy(update={"inline_keyboard": rows})

    return markup


def _localize_text(text: str | None) -> str | None:
    clean = sanitize_client_text(text)
    if clean is None or current_language() != KK:
        return clean

    exact = {
        "Документ пока не прошёл автоматическую юридическую проверку. Повторите подготовку документа. Если проверка снова не завершится, можно передать дело персональному юристу.": tr(KK, "claim_not_ready"),
        "✅ Проект иска сформирован в Word (.docx).\n\nПеред подачей проверьте реквизиты, суммы и приложения.": tr(KK, "claim_ready"),
        "Формирую и проверяю проект иска…": tr(KK, "claim_generating"),
        "Опишите обстоятельства дела одним сообщением — после этого сразу сформирую иск без анкеты по реквизитам.": tr(KK, "claim_waiting"),
        "Не удалось выполнить юридический поиск. Попробуйте повторить вопрос.": tr(KK, "consult_error"),
    }
    if clean in exact:
        return exact[clean]

    replacements = (
        ("Официальные источники:", "Ресми дереккөздер:"),
        ("Иск сформирован в Word (.docx).", "Талап қою арызы Word (.docx) форматында дайын."),
        ("Проект иска сформирован", "Талап қою арызының жобасы дайын"),
        ("Перед подачей требуется:", "Сотқа берер алдында қажет:"),
        ("Перед подачей проверьте:", "Сотқа берер алдында тексеріңіз:"),
        ("Юридическое содержание прошло порог качества.", "Құқықтық мазмұн сапа шегінен өтті."),
        ("Перед подачей нужно заполнить/проверить реквизиты:", "Сотқа берер алдында деректемелерді толтыру/тексеру қажет:"),
    )
    for source, target in replacements:
        clean = clean.replace(source, target)
    return clean


def _prepare_send_document(method: SendDocument, language: str | None = None) -> SendDocument:
    """Apply client-safe presentation to the actual Telegram SendDocument method.

    Message.answer_document() bypasses Bot.send_document() and executes a
    SendDocument method through Bot.__call__.  Intercepting here therefore covers
    the real claim/pretrial/response/contract delivery paths without changing any
    legal generator or router.
    """
    lang = language or current_language()
    kind = _generated_document_kind(method.document)
    update: dict[str, Any] = {"document": _clean_upload(method.document)}
    if kind is not None:
        update["caption"] = _document_caption_with_review(kind, lang)
        update["reply_markup"] = _document_review_markup(kind, lang)
    else:
        if method.caption is not None:
            update["caption"] = _localize_text(method.caption)
        if method.reply_markup is not None:
            update["reply_markup"] = _localize_markup(method.reply_markup)
    return method.model_copy(update=update)


class LocalizedClientSafeBot(ClientSafeBot):
    """Client-safe transport plus per-session Russian/Kazakh presentation."""

    async def __call__(self, method: Any, request_timeout: int | None = None) -> Any:
        if isinstance(method, SendDocument):
            method = _prepare_send_document(method)
        return await super().__call__(method, request_timeout=request_timeout)

    async def send_message(self, chat_id: Any, text: str, *args: Any, **kwargs: Any) -> Any:
        if "reply_markup" in kwargs:
            kwargs["reply_markup"] = _localize_markup(kwargs.get("reply_markup"))
        return await Bot.send_message(self, chat_id, _localize_text(text) or "", *args, **kwargs)

    async def send_document(self, chat_id: Any, document: Any, *args: Any, **kwargs: Any) -> Any:
        document_kind = _generated_document_kind(document)
        language = current_language()

        if document_kind is not None:
            kwargs["caption"] = _document_caption_with_review(document_kind, language)
            kwargs["reply_markup"] = _document_review_markup(document_kind, language)
        else:
            if "caption" in kwargs:
                kwargs["caption"] = _localize_text(kwargs.get("caption"))
            if "reply_markup" in kwargs:
                kwargs["reply_markup"] = _localize_markup(kwargs.get("reply_markup"))

        return await Bot.send_document(self, chat_id, _clean_upload(document), *args, **kwargs)

    async def edit_message_text(self, text: str, *args: Any, **kwargs: Any) -> Any:
        if "reply_markup" in kwargs:
            kwargs["reply_markup"] = _localize_markup(kwargs.get("reply_markup"))
        return await Bot.edit_message_text(self, _localize_text(text) or "", *args, **kwargs)

    async def edit_message_caption(self, *args: Any, **kwargs: Any) -> Any:
        if "caption" in kwargs:
            kwargs["caption"] = _localize_text(kwargs.get("caption"))
        if "reply_markup" in kwargs:
            kwargs["reply_markup"] = _localize_markup(kwargs.get("reply_markup"))
        return await Bot.edit_message_caption(self, *args, **kwargs)
