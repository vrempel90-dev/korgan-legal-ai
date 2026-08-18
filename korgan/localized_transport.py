from __future__ import annotations

from typing import Any
from urllib.parse import quote

from aiogram import Bot
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
}


def _generated_document_kind(document: Any) -> str | None:
    filename = str(getattr(document, "filename", "") or "").rsplit("/", 1)[-1].lower()
    return _DOCUMENT_KINDS.get(filename)


def _document_review_text(kind: str, language: str) -> str:
    if language == KK:
        intro = {
            "claim": "⚠️ Бұл талап қою арызы KORGAN AI көмегімен дайындалды. Сотқа берер алдында оны заңгерге тексертуге кеңес береміз.",
            "pretrial": "⚠️ Бұл сотқа дейінгі талап KORGAN AI көмегімен дайындалды. Жіберер алдында оны заңгерге тексертуге кеңес береміз.",
            "response": "⚠️ Бұл талап қою арызына пікір KORGAN AI көмегімен дайындалды. Сотқа ұсынар алдында оны заңгерге тексертуге кеңес береміз.",
            "contract": "⚠️ Бұл шарт жобасы KORGAN AI көмегімен дайындалды. Қол қояр алдында оны заңгерге тексертуге кеңес береміз.",
        }[kind]
        scope = {
            "claim": "Тексеру тек осы талап қою арызына қатысты.",
            "pretrial": "Тексеру тек осы сотқа дейінгі талапқа қатысты.",
            "response": "Тексеру тек осы пікірге қатысты.",
            "contract": "Тексеру тек осы шарт жобасына қатысты.",
        }[kind]
        return (
            f"{intro}\n\n{scope} Қосымша құжаттарды дайындау немесе тексеру және өзге заңгерлік жұмыс — бөлек ақылы қызмет.\n\n"
            "WhatsApp ашылғаннан кейін осы чатта алған Word файлын заңгерге тіркеңіз."
        )

    intro = {
        "claim": "⚠️ Этот иск подготовлен с использованием KORGAN AI. Перед подачей в суд рекомендуем проверить его у юриста.",
        "pretrial": "⚠️ Эта досудебная претензия подготовлена с использованием KORGAN AI. Перед направлением адресату рекомендуем проверить её у юриста.",
        "response": "⚠️ Этот отзыв на иск подготовлен с использованием KORGAN AI. Перед подачей в суд рекомендуем проверить его у юриста.",
        "contract": "⚠️ Этот проект договора подготовлен с использованием KORGAN AI. Перед подписанием рекомендуем проверить его у юриста.",
    }[kind]
    scope = {
        "claim": "Проверка относится только к этому иску.",
        "pretrial": "Проверка относится только к этой досудебной претензии.",
        "response": "Проверка относится только к этому отзыву на иск.",
        "contract": "Проверка относится только к этому проекту договора.",
    }[kind]
    return (
        f"{intro}\n\n{scope} Подготовка или проверка дополнительных документов и иная юридическая работа — отдельная платная услуга.\n\n"
        "После открытия WhatsApp прикрепите полученный в этом чате Word-файл."
    )


def _document_review_markup(kind: str, language: str) -> InlineKeyboardMarkup:
    if language == KK:
        label = {
            "claim": "👨‍⚖️ Талапты WhatsApp-та тексеру",
            "pretrial": "👨‍⚖️ Сотқа дейінгі талапты тексеру",
            "response": "👨‍⚖️ Пікірді WhatsApp-та тексеру",
            "contract": "👨‍⚖️ Шартты WhatsApp-та тексеру",
        }[kind]
        subject = {
            "claim": "талап қою арызын",
            "pretrial": "сотқа дейінгі талапты",
            "response": "талап қою арызына пікірді",
            "contract": "шарт жобасын",
        }[kind]
        text = f"Сәлеметсіз бе! KORGAN-да дайындалған {subject} заңгерге тексеруге бергім келеді. Қазір Word файлын тіркеймін."
    else:
        label = {
            "claim": "👨‍⚖️ Проверить иск в WhatsApp",
            "pretrial": "👨‍⚖️ Проверить претензию в WhatsApp",
            "response": "👨‍⚖️ Проверить отзыв в WhatsApp",
            "contract": "👨‍⚖️ Проверить договор в WhatsApp",
        }[kind]
        subject = {
            "claim": "иск",
            "pretrial": "досудебную претензию",
            "response": "отзыв на иск",
            "contract": "проект договора",
        }[kind]
        text = f"Здравствуйте! Хочу передать {subject}, подготовленный в KORGAN, на проверку юристу. Сейчас прикреплю Word-файл."

    url = f"https://wa.me/{_REVIEW_PHONE}?text={quote(text)}"
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=label, url=url)]])


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


class LocalizedClientSafeBot(ClientSafeBot):
    """Client-safe transport plus per-session Russian/Kazakh presentation."""

    async def send_message(self, chat_id: Any, text: str, *args: Any, **kwargs: Any) -> Any:
        if "reply_markup" in kwargs:
            kwargs["reply_markup"] = _localize_markup(kwargs.get("reply_markup"))
        return await Bot.send_message(self, chat_id, _localize_text(text) or "", *args, **kwargs)

    async def send_document(self, chat_id: Any, document: Any, *args: Any, **kwargs: Any) -> Any:
        document_kind = _generated_document_kind(document)
        if "caption" in kwargs:
            kwargs["caption"] = _localize_text(kwargs.get("caption"))
        if "reply_markup" in kwargs:
            kwargs["reply_markup"] = _localize_markup(kwargs.get("reply_markup"))

        result = await Bot.send_document(self, chat_id, _clean_upload(document), *args, **kwargs)

        # CTA is intentionally post-delivery and non-blocking: it can never turn
        # a successfully generated legal document into a failed request.
        if document_kind is not None:
            language = current_language()
            try:
                await Bot.send_message(
                    self,
                    chat_id,
                    _document_review_text(document_kind, language),
                    reply_markup=_document_review_markup(document_kind, language),
                )
            except Exception:
                pass
        return result

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
