from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from openai import AsyncOpenAI

from korgan.config import Settings
from korgan.i18n import KK


_KIND_RU = {
    "claim": "исковое заявление",
    "pretrial": "досудебную претензию",
    "response": "отзыв на иск",
    "contract": "договор",
}
_KIND_KK = {
    "claim": "талап қою арызы",
    "pretrial": "сотқа дейінгі талап",
    "response": "талап қою арызына пікір",
    "contract": "шарт",
}

_RECEIPT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "readable": {"type": "boolean"},
        "looks_like_kaspi": {"type": "boolean"},
        "payment_successful": {"type": "boolean"},
        "amount_kzt": {"type": "integer"},
        "date_time": {"type": "string"},
        "merchant_or_recipient": {"type": "string"},
        "payer": {"type": "string"},
        "receipt_or_transaction_id": {"type": "string"},
        "rnm": {"type": "string"},
        "fp": {"type": "string"},
        "suspicious_signals": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "readable",
        "looks_like_kaspi",
        "payment_successful",
        "amount_kzt",
        "date_time",
        "merchant_or_recipient",
        "payer",
        "receipt_or_transaction_id",
        "rnm",
        "fp",
        "suspicious_signals",
        "notes",
    ],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class ReceiptCheck:
    readable: bool
    looks_like_kaspi: bool
    payment_successful: bool
    amount_kzt: int
    date_time: str
    merchant_or_recipient: str
    payer: str
    receipt_or_transaction_id: str
    rnm: str
    fp: str
    suspicious_signals: tuple[str, ...]
    notes: tuple[str, ...]

    @property
    def hard_failure(self) -> bool:
        return not self.readable or not self.looks_like_kaspi or not self.payment_successful


class ReceiptAnalyzer:
    """AI pre-check only. Final payment confirmation is always manual/admin-side."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)

    async def analyze(self, data: bytes, filename: str, mime_type: str) -> ReceiptCheck:
        suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        encoded = base64.b64encode(data).decode("ascii")
        prompt = (
            "Проведи предварительную проверку чека оплаты KORGAN. Извлеки только то, что реально видно. "
            "Определи, похож ли документ на чек/квитанцию Kaspi, отмечена ли оплата как успешная, сумму, дату/время, "
            "получателя, плательщика, номер операции/чека, РНМ и ФП при наличии. Отдельно перечисли визуальные признаки "
            "возможного редактирования, обрезки критичных полей, несовпадающих шрифтов/слоёв или иных аномалий. "
            "Не называй чек подлинным: у тебя нет прямого доступа к Kaspi Pay/ОФД. Если поле не видно — оставь пустую строку, "
            "для суммы используй 0."
        )
        if suffix == "pdf" or mime_type == "application/pdf":
            content: list[dict[str, Any]] = [{
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_file", "filename": filename, "file_data": encoded},
                ],
            }]
        else:
            media = mime_type or "image/jpeg"
            content = [{
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": f"data:{media};base64,{encoded}", "detail": "high"},
                ],
            }]

        response = await self.client.responses.create(
            model=self.settings.openai_vision_model,
            instructions=(
                "Ты модуль антифрода KORGAN. Работай консервативно: не выдумывай реквизиты и не подтверждай банковский факт оплаты. "
                "Твоя задача — только предварительная визуальная/реквизитная проверка перед обязательной ручной сверкой администратором."
            ),
            input=content,
            text={"format": {"type": "json_schema", "name": "korgan_receipt_check", "schema": _RECEIPT_SCHEMA, "strict": True}},
            store=False,
        )
        payload = json.loads(response.output_text)
        return ReceiptCheck(
            readable=bool(payload["readable"]),
            looks_like_kaspi=bool(payload["looks_like_kaspi"]),
            payment_successful=bool(payload["payment_successful"]),
            amount_kzt=int(payload["amount_kzt"] or 0),
            date_time=str(payload["date_time"] or ""),
            merchant_or_recipient=str(payload["merchant_or_recipient"] or ""),
            payer=str(payload["payer"] or ""),
            receipt_or_transaction_id=str(payload["receipt_or_transaction_id"] or ""),
            rnm=str(payload["rnm"] or ""),
            fp=str(payload["fp"] or ""),
            suspicious_signals=tuple(str(x) for x in payload["suspicious_signals"]),
            notes=tuple(str(x) for x in payload["notes"]),
        )


def document_label(kind: str, language: str) -> str:
    return (_KIND_KK if language == KK else _KIND_RU)[kind]


def _secret(settings: Settings) -> bytes:
    return settings.telegram_bot_token.encode("utf-8")


def sign_user_payment(settings: Settings, user_id: int, admin_doc_message_id: int, kind: str, language: str) -> str:
    body = f"user:{user_id}:{admin_doc_message_id}:{kind}:{language}".encode("utf-8")
    return hmac.new(_secret(settings), body, hashlib.sha256).hexdigest()[:12]


def verify_user_payment(settings: Settings, signature: str, user_id: int, admin_doc_message_id: int, kind: str, language: str) -> bool:
    expected = sign_user_payment(settings, user_id, admin_doc_message_id, kind, language)
    return hmac.compare_digest(signature, expected)


def sign_admin_action(settings: Settings, user_id: int, admin_doc_message_id: int, kind: str, language: str) -> str:
    body = f"admin:{user_id}:{admin_doc_message_id}:{kind}:{language}".encode("utf-8")
    return hmac.new(_secret(settings), body, hashlib.sha256).hexdigest()[:12]


def verify_admin_action(settings: Settings, signature: str, user_id: int, admin_doc_message_id: int, kind: str, language: str) -> bool:
    expected = sign_admin_action(settings, user_id, admin_doc_message_id, kind, language)
    return hmac.compare_digest(signature, expected)


def payment_offer_text(kind: str, language: str, amount: int) -> str:
    label = document_label(kind, language)
    if language == KK:
        return (
            "💳 Құжат дайын\n\n"
            f"Қызмет құны: {amount:,} ₸".replace(",", " ")
            + f"\nҚұжат: {label}.\n\n"
            "Word-файл төлем расталғаннан кейін ғана беріледі.\n"
            "1. Kaspi арқылы төлеңіз.\n"
            "2. «✅ Төледім» түймесін басыңыз.\n"
            "3. Толық чекті жіберіңіз.\n\n"
            "Чек алдымен AI арқылы тексеріледі, содан кейін төлемді әкімші Kaspi Pay тарихымен растайды."
        )
    return (
        "💳 Документ готов\n\n"
        f"Стоимость: {amount:,} ₸".replace(",", " ")
        + f"\nДокумент: {label}.\n\n"
        "Word-файл будет выдан только после подтверждения оплаты.\n"
        "1. Оплатите через Kaspi.\n"
        "2. Нажмите «✅ Я оплатил».\n"
        "3. Пришлите полный чек.\n\n"
        "Чек сначала проходит AI-проверку, затем администратор подтверждает платёж по истории Kaspi Pay."
    )


def payment_offer_markup(settings: Settings, user_id: int, admin_doc_message_id: int, kind: str, language: str) -> InlineKeyboardMarkup:
    sig = sign_user_payment(settings, user_id, admin_doc_message_id, kind, language)
    paid_text = "✅ Төледім" if language == KK else "✅ Я оплатил"
    pay_text = "💳 Kaspi арқылы төлеу" if language == KK else "💳 Оплатить через Kaspi"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=pay_text, url=settings.kaspi_payment_url)],
        [InlineKeyboardButton(text=paid_text, callback_data=f"pay:proof:{admin_doc_message_id}:{kind}:{language}:{sig}")],
    ])


def admin_storage_caption(user_id: int, kind: str, language: str, amount: int) -> str:
    return (
        "🔒 KORGAN PAYMENT HOLD\n"
        f"Клиент Telegram ID: {user_id}\n"
        f"Документ: {document_label(kind, language)}\n"
        f"Сумма: {amount} ₸\n"
        "Не выдавать до подтверждения оплаты."
    )


def receipt_hard_issues(check: ReceiptCheck, expected_amount: int) -> list[str]:
    issues: list[str] = []
    if not check.readable:
        issues.append("чек не читается полностью")
    if not check.looks_like_kaspi:
        issues.append("документ не распознан как чек/квитанция Kaspi")
    if not check.payment_successful:
        issues.append("на чеке не подтверждён успешный платёж")
    if check.amount_kzt != expected_amount:
        issues.append(f"сумма на чеке {check.amount_kzt} ₸ вместо {expected_amount} ₸")
    return issues


def admin_receipt_summary(check: ReceiptCheck | None, *, user_id: int, kind: str, language: str, amount: int, ai_error: str = "") -> str:
    lines = [
        "💳 KORGAN — ПРОВЕРКА ОПЛАТЫ",
        "",
        f"Клиент Telegram ID: {user_id}",
        f"Документ: {document_label(kind, language)}",
        f"Ожидаемая сумма: {amount} ₸",
    ]
    if check is None:
        lines += ["", "⚠️ AI-проверка недоступна. Требуется полная ручная сверка."]
        if ai_error:
            lines.append(f"Техническая причина: {ai_error[:180]}")
    else:
        lines += [
            "",
            f"AI: Kaspi-похожий чек: {'да' if check.looks_like_kaspi else 'нет'}",
            f"AI: успешная оплата: {'да' if check.payment_successful else 'нет'}",
            f"Сумма на чеке: {check.amount_kzt} ₸",
            f"Дата/время: {check.date_time or 'не распознано'}",
            f"Получатель: {check.merchant_or_recipient or 'не распознан'}",
            f"Плательщик: {check.payer or 'не распознан'}",
            f"Операция/чек: {check.receipt_or_transaction_id or 'не распознано'}",
            f"РНМ: {check.rnm or 'не распознан'}",
            f"ФП: {check.fp or 'не распознан'}",
        ]
        if check.suspicious_signals:
            lines += ["", "⚠️ AI отметил аномалии:", *[f"• {x}" for x in check.suspicious_signals[:6]]]
    lines += ["", "Перед подтверждением обязательно сверить реальный платёж в Kaspi Pay → История."]
    return "\n".join(lines)


def admin_decision_markup(settings: Settings, user_id: int, admin_doc_message_id: int, kind: str, language: str) -> InlineKeyboardMarkup:
    sig = sign_admin_action(settings, user_id, admin_doc_message_id, kind, language)
    base = f"{user_id}:{admin_doc_message_id}:{kind}:{language}:{sig}"
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Подтвердить оплату", callback_data=f"pay:ok:{base}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"pay:no:{base}"),
    ]])
