from __future__ import annotations

import logging
import re
import secrets
import time
from dataclasses import dataclass
from urllib.parse import quote

import aiohttp
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from korgan.config import Settings, get_settings
from korgan.i18n import KK, RU, normalize_language

LOGGER = logging.getLogger(__name__)
router = Router(name="korgan-claim-review-handoff")

LAWYER_WHATSAPP_DISPLAY = "+7 700 500 05 53"
LAWYER_WHATSAPP_NUMBER = "77005000553"
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_PENDING_TTL_SECONDS = 2 * 60 * 60


class WhatsAppDeliveryError(RuntimeError):
    pass


@dataclass(slots=True)
class PendingClaimReview:
    chat_id: int
    data: bytes
    filename: str
    language: str
    reference: str
    created_monotonic: float
    status: str = "offered"
    wamid: str = ""


_PENDING: dict[int, PendingClaimReview] = {}


def _purge_expired() -> None:
    now = time.monotonic()
    expired = [
        chat_id
        for chat_id, item in _PENDING.items()
        if now - item.created_monotonic > _PENDING_TTL_SECONDS
    ]
    for chat_id in expired:
        _PENDING.pop(chat_id, None)


def new_review_reference() -> str:
    return "KORGAN-" + secrets.token_hex(3).upper()


def is_claim_review_document(filename: str | None) -> bool:
    return str(filename or "").lower() == "korgan_iskovoe_zayavlenie.docx"


def register_claim_for_review(
    chat_id: int,
    data: bytes,
    filename: str,
    language: str,
) -> PendingClaimReview:
    _purge_expired()
    item = PendingClaimReview(
        chat_id=chat_id,
        data=bytes(data),
        filename=filename,
        language=normalize_language(language),
        reference=new_review_reference(),
        created_monotonic=time.monotonic(),
    )
    _PENDING[chat_id] = item
    return item


def pending_claim_for_review(chat_id: int) -> PendingClaimReview | None:
    _purge_expired()
    return _PENDING.get(chat_id)


def discard_claim_review(chat_id: int) -> None:
    _PENDING.pop(chat_id, None)


def claim_review_offer_text(language: str = RU) -> str:
    if normalize_language(language) == KK:
        return (
            "👨‍⚖️ Маңызды: сотқа берер алдында\n\n"
            "Талап қою арызы KORGAN жасанды интеллектінің көмегімен дайындалды. Автоматты тексерулерге қарамастан, "
            "құжатта қате немесе дәлсіздік қалуы мүмкін. Сотқа бергенге дейін тірі заңгердің тексеруінен өткізуді ұсынамыз.\n\n"
            "Осы талап қою арызын KORGAN заңгеріне ақылы тексеруге жібересіз бе?\n\n"
            "Тексеру тек осы талап қою арызына қатысты. Егер кейін қосымша құжаттар, жаңа өтініштер, шағымдар, "
            "өтінішхаттар немесе өзге заңгерлік жұмыс қажет болса, олардың құны бөлек келісіледі және бөлек төленеді."
        )
    return (
        "👨‍⚖️ Важно перед подачей в суд\n\n"
        "Иск подготовлен KORGAN с использованием искусственного интеллекта. Несмотря на автоматические проверки, "
        "в документе могут остаться ошибки или неточности. Перед подачей в суд рекомендуем проверку живым юристом.\n\n"
        "Передать этот иск юристу KORGAN на платную проверку?\n\n"
        "Проверка относится только к этому иску. Если после проверки понадобятся дополнительные документы, новые "
        "заявления, жалобы, ходатайства или иная юридическая работа, их стоимость согласовывается и оплачивается отдельно."
    )


def claim_review_offer_markup(language: str = RU) -> InlineKeyboardMarkup:
    kk = normalize_language(language) == KK
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="👨‍⚖️ Талап қою арызын тексеруге жіберу" if kk else "👨‍⚖️ Передать иск на проверку",
                callback_data="claimreview:offer",
            )],
            [InlineKeyboardButton(
                text="❌ Жібермеу" if kk else "❌ Не передавать",
                callback_data="claimreview:cancel",
            )],
        ]
    )


def claim_review_consent_text(language: str = RU) -> str:
    if normalize_language(language) == KK:
        return (
            "🔐 Деректерді беруге келісім\n\n"
            "Тексеру үшін KORGAN заңгерге сізге берілген осы Word-файлды және оның ішінде көрсетілген деректерді береді.\n\n"
            "«Келісемін және жіберемін» батырмасын басу арқылы сіз осы талап қою арызын және оның ішіндегі деректерді "
            "тек осы құжатты тексеру және өтінімді қарау мақсатында KORGAN заңгеріне беруге келісесіз.\n\n"
            "Тексерудің бағасы мен шарттары ақылы жұмыс басталғанға дейін заңгермен келісіледі. Қосымша құжаттар мен "
            "осы талап қою арызын тексеруге кірмейтін өзге жұмыс бөлек төленеді. Өтінімді жіберу өздігінен шарт жасалды "
            "дегенді білдірмейді және іс нәтижесіне кепілдік бермейді."
        )
    return (
        "🔐 Согласие на передачу данных\n\n"
        "Для проверки KORGAN передаст юристу тот Word-файл иска, который был выдан вам, и данные, содержащиеся в нём.\n\n"
        "Нажимая «Согласен и передать», вы соглашаетесь на передачу этого иска и содержащихся в нём данных юристу "
        "KORGAN исключительно для рассмотрения заявки и проверки данного иска.\n\n"
        "Стоимость и условия проверки согласовываются с юристом до начала платной работы. Дополнительные документы "
        "и иная работа, не входящая в проверку этого иска, оплачиваются отдельно. Передача заявки сама по себе не "
        "означает заключение договора и не гарантирует результат по делу."
    )


def claim_review_consent_markup(language: str = RU) -> InlineKeyboardMarkup:
    kk = normalize_language(language) == KK
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="✅ Келісемін және жіберемін" if kk else "✅ Согласен и передать",
                callback_data="claimreview:confirm",
            )],
            [InlineKeyboardButton(
                text="↩️ Болдырмау" if kk else "↩️ Отмена",
                callback_data="claimreview:cancel",
            )],
        ]
    )


def _digits(value: str) -> str:
    return re.sub(r"\D+", "", value or "")


def lawyer_chat_url(reference: str, language: str = RU, number: str = LAWYER_WHATSAPP_NUMBER) -> str:
    if normalize_language(language) == KK:
        text = f"Сәлеметсіз бе! Менің талап қою арызым KORGAN арқылы тексеруге жіберілді. Өтінім коды: {reference}."
    else:
        text = f"Здравствуйте! Мой иск передан через KORGAN на проверку. Код заявки: {reference}."
    return f"https://wa.me/{_digits(number)}?text={quote(text)}"


def lawyer_chat_markup(reference: str, language: str = RU, number: str = LAWYER_WHATSAPP_NUMBER) -> InlineKeyboardMarkup:
    kk = normalize_language(language) == KK
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="💬 Заңгермен WhatsApp-та сөйлесу" if kk else "💬 Открыть чат с юристом",
                url=lawyer_chat_url(reference, language, number),
            )]
        ]
    )


def success_text(reference: str, language: str = RU) -> str:
    if normalize_language(language) == KK:
        return (
            f"✅ Өтінім {reference} заңгерге талап қою арызымен бірге WhatsApp арқылы жіберілді.\n\n"
            "Төмендегі батырманы басып, заңгермен чат ашыңыз. Дайын хабарламадағы өтінім коды құжатты сіздің чатыңызбен сәйкестендіреді."
        )
    return (
        f"✅ Заявка {reference} передана юристу в WhatsApp вместе с иском.\n\n"
        "Откройте чат кнопкой ниже. Код в уже подготовленном сообщении позволит юристу сопоставить ваш чат с полученным документом."
    )


def build_media_template_payload(
    settings: Settings,
    media_id: str,
    filename: str,
) -> dict:
    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": _digits(settings.whatsapp_lawyer_number),
        "type": "template",
        "template": {
            "name": settings.whatsapp_review_template_name,
            "language": {"code": settings.whatsapp_review_template_language},
            "components": [
                {
                    "type": "header",
                    "parameters": [
                        {
                            "type": "document",
                            "document": {"id": media_id, "filename": filename},
                        }
                    ],
                }
            ],
        },
    }


class WhatsAppClaimReviewSender:
    """Upload the exact claim file to Meta and send it to the lawyer with an approved media template."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def _base_url(self) -> str:
        version = self.settings.whatsapp_graph_api_version.strip().strip("/")
        return f"https://graph.facebook.com/{version}"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.settings.whatsapp_access_token}"}

    async def _upload_document(self, session: aiohttp.ClientSession, data: bytes, filename: str) -> str:
        form = aiohttp.FormData()
        form.add_field("messaging_product", "whatsapp")
        form.add_field("file", data, filename=filename, content_type=_DOCX_MIME)
        url = f"{self._base_url()}/{self.settings.whatsapp_phone_number_id}/media"
        async with session.post(url, headers=self._headers(), data=form) as response:
            payload = await response.json(content_type=None)
            if response.status >= 300 or not payload.get("id"):
                raise WhatsAppDeliveryError(f"WhatsApp media upload failed status={response.status} payload={payload}")
            return str(payload["id"])

    async def _send_template(self, session: aiohttp.ClientSession, media_id: str, filename: str) -> str:
        url = f"{self._base_url()}/{self.settings.whatsapp_phone_number_id}/messages"
        headers = {**self._headers(), "Content-Type": "application/json"}
        body = build_media_template_payload(self.settings, media_id, filename)
        async with session.post(url, headers=headers, json=body) as response:
            payload = await response.json(content_type=None)
            messages = payload.get("messages") or []
            wamid = messages[0].get("id") if messages and isinstance(messages[0], dict) else None
            if response.status >= 300 or not wamid:
                raise WhatsAppDeliveryError(f"WhatsApp template send failed status={response.status} payload={payload}")
            return str(wamid)

    async def send_claim(self, data: bytes, filename: str) -> str:
        if not self.settings.whatsapp_review_ready:
            raise WhatsAppDeliveryError("WhatsApp lawyer review is not configured")
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            media_id = await self._upload_document(session, data, filename)
            return await self._send_template(session, media_id, filename)


@router.callback_query(F.data == "claimreview:offer")
async def claim_review_offer(callback: CallbackQuery, state: FSMContext) -> None:
    chat_id = callback.message.chat.id if callback.message is not None else None
    data = await state.get_data()
    language = normalize_language(str(data.get("language", RU)))
    if chat_id is None or pending_claim_for_review(chat_id) is None:
        await callback.answer(
            "Иск уже недоступен. Сформируйте его заново." if language != KK else "Талап қою арызы қолжетімсіз. Оны қайта дайындаңыз.",
            show_alert=True,
        )
        return
    await callback.answer()
    if callback.message is not None:
        await callback.message.edit_text(
            claim_review_consent_text(language),
            reply_markup=claim_review_consent_markup(language),
        )


@router.callback_query(F.data == "claimreview:cancel")
async def claim_review_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    chat_id = callback.message.chat.id if callback.message is not None else None
    await callback.answer()
    if chat_id is not None:
        discard_claim_review(chat_id)
    if callback.message is not None:
        await callback.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data == "claimreview:confirm")
async def claim_review_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    settings = get_settings()
    data = await state.get_data()
    language = normalize_language(str(data.get("language", RU)))
    chat_id = callback.message.chat.id if callback.message is not None else None
    pending = pending_claim_for_review(chat_id) if chat_id is not None else None

    if pending is None:
        await callback.answer(
            "Иск уже недоступен. Сформируйте его заново." if language != KK else "Талап қою арызы қолжетімсіз. Оны қайта дайындаңыз.",
            show_alert=True,
        )
        return

    if pending.status == "sent":
        await callback.answer()
        if callback.message is not None:
            await callback.message.edit_text(
                success_text(pending.reference, language),
                reply_markup=lawyer_chat_markup(pending.reference, language, settings.whatsapp_lawyer_number),
            )
        return

    if not settings.whatsapp_review_ready:
        LOGGER.error("CLAIM_REVIEW_WHATSAPP_NOT_CONFIGURED reference=%s", pending.reference)
        await callback.answer(
            "Передача в WhatsApp пока не настроена. Заявка не отправлена."
            if language != KK else
            "WhatsApp арқылы жіберу әлі бапталмаған. Өтінім жіберілген жоқ.",
            show_alert=True,
        )
        return

    await callback.answer()
    if callback.message is not None:
        await callback.message.edit_reply_markup(reply_markup=None)

    filename = f"{pending.reference}_isk_na_proverku.docx"
    try:
        wamid = await WhatsAppClaimReviewSender(settings).send_claim(pending.data, filename)
    except Exception:
        LOGGER.exception("CLAIM_REVIEW_WHATSAPP_FAILED reference=%s", pending.reference)
        if callback.message is not None:
            await callback.message.edit_text(
                "❌ Не удалось передать иск в WhatsApp. Заявка не считается отправленной. Попробуйте ещё раз позже."
                if language != KK else
                "❌ Талап қою арызын WhatsApp арқылы жіберу мүмкін болмады. Өтінім жіберілген болып есептелмейді. Кейінірек қайталап көріңіз.",
                reply_markup=claim_review_consent_markup(language),
            )
        return

    pending.status = "sent"
    pending.wamid = wamid
    pending.data = b""
    LOGGER.info("CLAIM_REVIEW_WHATSAPP_SENT reference=%s wamid=%s", pending.reference, wamid)
    if callback.message is not None:
        await callback.message.edit_text(
            success_text(pending.reference, language),
            reply_markup=lawyer_chat_markup(pending.reference, language, settings.whatsapp_lawyer_number),
        )
