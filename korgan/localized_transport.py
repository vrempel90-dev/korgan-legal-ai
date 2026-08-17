from __future__ import annotations

from typing import Any

from aiogram import Bot
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from korgan.case_reference import (
    case_reference_from_filename,
    document_kind_from_filename,
    document_label,
    new_case_reference,
)
from korgan.client_safe_ui import ClientSafeBot, _clean_upload, sanitize_client_text
from korgan.contact_handlers import WHATSAPP_NUMBER_DISPLAY, whatsapp_url_for_case
from korgan.i18n import BUTTONS, KK, RU, tr
from korgan.language_context import current_language

_BUTTON_MAP = {value: BUTTONS[KK][key] for key, value in BUTTONS[RU].items()}


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


def _generated_filename(document: Any) -> str:
    return str(getattr(document, "filename", "") or "")


def is_generated_korgan_document(document: Any) -> bool:
    """Only KORGAN-produced DOCX/PDF files receive the post-document CTA."""
    filename = _generated_filename(document).lower()
    return filename.startswith("korgan_") and filename.endswith((".docx", ".pdf"))


def short_document_caption(filename: str, language: str = RU) -> str:
    """Client-facing caption deliberately contains no internal quality dump."""
    name = (filename or "").lower()
    kk = language == KK
    if "otzyv" in name or "response" in name:
        return "✅ Талап қоюға пікір дайын." if kk else "✅ Отзыв на иск готов."
    if "dosudeb" in name or "sotqa_deyingi" in name or "pretrial" in name:
        return "✅ Сотқа дейінгі талап дайын." if kk else "✅ Досудебная претензия готова."
    if "dogovor" in name or "contract" in name:
        return "✅ Шарт дайын." if kk else "✅ Договор готов."
    if "iskov" in name or "claim" in name:
        return "✅ Талап қою арызы дайын." if kk else "✅ Исковое заявление готово."
    return "✅ Құжат дайын." if kk else "✅ Документ готов."


def lawyer_consultation_text(
    language: str,
    case_reference: str,
    document_kind: str,
) -> str:
    label = document_label(document_kind, language)
    if language == KK:
        return (
            f"👨‍⚖️ KORGAN ісі № {case_reference}\n"
            f"📄 Құжат: {label}\n\n"
            "Құжатты пайдаланар алдында заңгердің қорытынды консультациясы қажет.\n"
            "Жеке заңгердің консультациясы ақылы. Осы іс бойынша консультация алғыңыз келе ме?\n\n"
            f"📱 {WHATSAPP_NUMBER_DISPLAY}"
        )
    return (
        f"👨‍⚖️ Дело KORGAN № {case_reference}\n"
        f"📄 Документ: {label}\n\n"
        "Перед использованием документа требуется финальная консультация юриста.\n"
        "Консультация персонального юриста платная. Хотите получить консультацию по этому делу?\n\n"
        f"📱 {WHATSAPP_NUMBER_DISPLAY}"
    )


def lawyer_consultation_markup(
    language: str,
    case_reference: str,
    document_kind: str,
) -> InlineKeyboardMarkup:
    yes = "✅ Иә" if language == KK else "✅ Да"
    no = "❌ Жоқ" if language == KK else "❌ Нет"
    # URL button opens WhatsApp immediately in one tap. The case reference and
    # document type are included in the pre-filled WhatsApp message.
    url = whatsapp_url_for_case(case_reference, document_kind, language)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=yes, url=url)],
            [InlineKeyboardButton(text=no, callback_data="lawyer:decline")],
        ]
    )


class LocalizedClientSafeBot(ClientSafeBot):
    """Client-safe transport plus per-session RU/KK and direct lawyer CTA."""

    async def send_message(self, chat_id: Any, text: str, *args: Any, **kwargs: Any) -> Any:
        if "reply_markup" in kwargs:
            kwargs["reply_markup"] = _localize_markup(kwargs.get("reply_markup"))
        return await Bot.send_message(self, chat_id, _localize_text(text) or "", *args, **kwargs)

    async def send_document(self, chat_id: Any, document: Any, *args: Any, **kwargs: Any) -> Any:
        generated = is_generated_korgan_document(document)
        filename = _generated_filename(document)
        language = current_language()

        if generated:
            # Replace long quality/verification captions with one clean result.
            kwargs["caption"] = short_document_caption(filename, language)
        elif "caption" in kwargs:
            kwargs["caption"] = _localize_text(kwargs.get("caption"))

        if "reply_markup" in kwargs:
            kwargs["reply_markup"] = _localize_markup(kwargs.get("reply_markup"))

        sent = await Bot.send_document(self, chat_id, _clean_upload(document), *args, **kwargs)

        if generated:
            case_reference = case_reference_from_filename(filename) or new_case_reference()
            document_kind = document_kind_from_filename(filename)
            await Bot.send_message(
                self,
                chat_id,
                lawyer_consultation_text(language, case_reference, document_kind),
                reply_markup=lawyer_consultation_markup(language, case_reference, document_kind),
                disable_web_page_preview=True,
            )
        return sent

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
