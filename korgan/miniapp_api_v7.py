from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import File, Header, HTTPException, UploadFile

from korgan import miniapp_api_v6 as v6
from korgan import miniapp_document_payments as payments
from korgan.kaspi_receipt_verifier import KaspiReceiptAnalyzer

app = v6.app
core = v6.core
settings = v6.settings
v5 = v6.v5
v4 = v5.v4
PARITY_REVISION = "2026-08-27.auto-payment-v7-kaspi-ofd"
_KZ_TZ = timezone(timedelta(hours=5))


def _configured_values(value: str) -> set[str]:
    return {part.strip() for part in re.split(r"[|;]+", str(value or "")) if part.strip()}


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = " ".join(str(value or "").strip().split())
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            parsed = None
            for fmt in (
                "%d.%m.%Y %H:%M:%S",
                "%d.%m.%Y %H:%M",
                "%Y-%m-%d %H:%M:%S.%f",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
            ):
                try:
                    parsed = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
            if parsed is None:
                return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_KZ_TZ)
    return parsed.astimezone(timezone.utc)


def _check_value(check: Any, name: str, default: Any = "") -> Any:
    if isinstance(check, dict):
        return check.get(name, default)
    return getattr(check, name, default)


def _strict_receipt_issues(check: Any, expected_amount: int, *, offered_at: Any) -> list[str]:
    issues: list[str] = []
    if not bool(_check_value(check, "readable", False)):
        issues.append("чек не читается полностью")
    if not bool(_check_value(check, "looks_like_kaspi", False)):
        issues.append("документ не распознан как фискальный чек Kaspi")
    if not bool(_check_value(check, "payment_successful", False)):
        issues.append("в чеке не подтверждена успешная оплата")

    amount = int(_check_value(check, "amount_kzt", 0) or 0)
    if amount != int(expected_amount):
        issues.append(f"сумма на чеке {amount} ₸ вместо {expected_amount} ₸")

    qr_url = str(_check_value(check, "qr_url", "") or "").strip()
    if not qr_url:
        issues.append("не удалось распознать QR фискального чека Kaspi")
    if not bool(_check_value(check, "official_verified", False)):
        issues.append("чек не подтверждён публичной страницей Kaspi ОФД")

    rnm = str(_check_value(check, "rnm", "") or "").strip()
    fp = str(_check_value(check, "fp", "") or "").strip()
    seller_bin = str(_check_value(check, "seller_bin", "") or "").strip()
    if not rnm:
        issues.append("в чеке не распознан РНМ")
    if not fp:
        issues.append("в чеке не распознан ФП")

    allowed_rnms = _configured_values(getattr(settings, "kaspi_rnm", ""))
    if not allowed_rnms:
        issues.append("РНМ KORGAN не настроен")
    elif rnm and rnm not in allowed_rnms:
        issues.append("РНМ чека не принадлежит кассе KORGAN")

    allowed_bins = _configured_values(getattr(settings, "kaspi_seller_bin", ""))
    if not allowed_bins:
        issues.append("БИН продавца KORGAN не настроен")
    elif seller_bin and seller_bin not in allowed_bins:
        issues.append("БИН продавца в чеке не соответствует KORGAN")

    date_time = str(_check_value(check, "date_time", "") or "").strip()
    if not date_time:
        issues.append("в чеке не распознаны дата/время платежа")
    else:
        receipt_time = _parse_datetime(date_time)
        offer_time = _parse_datetime(offered_at)
        if receipt_time is None:
            issues.append("дата/время платежа не распознаны в допустимом формате")
        elif offer_time is None:
            issues.append("не удалось подтвердить время открытия текущей оплаты")
        else:
            if receipt_time < offer_time - timedelta(minutes=2):
                issues.append("платёж выполнен до открытия текущей заявки на оплату")
            if receipt_time > datetime.now(timezone.utc) + timedelta(minutes=10):
                issues.append("дата/время платежа находятся недопустимо в будущем")

    suspicious = list(_check_value(check, "suspicious_signals", ()) or ())
    if suspicious:
        issues.append("обнаружены признаки возможного изменения или аномалии чека")
    return issues


def _receipt_check_payload(check: Any) -> dict[str, Any]:
    payload = v4._receipt_check_payload_original(check) if hasattr(v4, "_receipt_check_payload_original") else {
        "readable": bool(check.readable),
        "looks_like_kaspi": bool(check.looks_like_kaspi),
        "payment_successful": bool(check.payment_successful),
        "amount_kzt": int(check.amount_kzt or 0),
        "date_time": str(check.date_time or ""),
        "merchant_or_recipient": str(check.merchant_or_recipient or ""),
        "payer": str(check.payer or ""),
        "receipt_or_transaction_id": str(check.receipt_or_transaction_id or ""),
        "rnm": str(check.rnm or ""),
        "fp": str(check.fp or ""),
        "suspicious_signals": [str(x) for x in check.suspicious_signals],
        "notes": [str(x) for x in check.notes],
    }
    payload.update({
        "seller_bin": str(_check_value(check, "seller_bin", "") or ""),
        "qr_url": str(_check_value(check, "qr_url", "") or ""),
        "official_verified": bool(_check_value(check, "official_verified", False)),
        "official_final_url": str(_check_value(check, "official_final_url", "") or ""),
        "source": str(_check_value(check, "source", "") or ""),
    })
    return payload


if not hasattr(v4, "_receipt_check_payload_original"):
    v4._receipt_check_payload_original = v4._receipt_check_payload
v4._receipt_check_payload = _receipt_check_payload

v5._strict_receipt_issues = _strict_receipt_issues
v6._strict_receipt_issues = _strict_receipt_issues
v5.PARITY_REVISION = PARITY_REVISION


async def _auto_approve_stored(order: payments.DocumentPaymentOrder, *, user_key: str) -> payments.DocumentPaymentOrder:
    if order.status != "awaiting_admin":
        return order
    created_at = await v5._order_created_at(order.id, user_key)
    issues = _strict_receipt_issues(order.receipt_check or {}, order.amount_kzt, offered_at=created_at)
    if issues:
        return order
    await payments.decide_document_order(
        order.id,
        approved=True,
        note="Kaspi OFD deterministic verification passed (v7)",
    )
    latest = await payments.get_document_order(order.id, user_key=user_key)
    return latest or order


v5._auto_approve_stored = _auto_approve_stored


for _path, _method in (
    ("/miniapp/documents/payments/{order_id}/receipt", "POST"),
    ("/miniapp/parity", "GET"),
):
    v5._drop(_path, _method)


@app.get("/miniapp/parity")
async def parity() -> dict[str, Any]:
    payload = await v4.parity()
    payload.update({
        "api_version": "1.1.0",
        "parity_revision": PARITY_REVISION,
        "document_manual_confirmation": False,
        "document_payment_admin_configured": False,
        "automatic_receipt_verification": True,
        "receipt_verification_mode": "kaspi_ofd_qr_deterministic",
        "receipt_ai_decision": False,
    })
    return payload


@app.post("/miniapp/documents/payments/{order_id}/receipt")
async def document_payment_receipt(
    order_id: int,
    file: UploadFile = File(...),
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    identity = core.legacy._identity(x_telegram_init_data)
    await core.legacy._require_consent(identity)
    user_key = core.store.user_key(identity)
    order = await payments.get_document_order(order_id, user_key=user_key)
    if order is None:
        raise HTTPException(status_code=404, detail="Платёжный запрос не найден")
    if order.status == "approved":
        return {
            "ok": True,
            "payment_required": False,
            "payment": v5._payment_payload(order),
            "message": "Оплата уже подтверждена.",
        }
    if order.status not in {"pending_receipt", "awaiting_admin"}:
        raise HTTPException(status_code=409, detail="Этот платёжный запрос уже закрыт")

    filename = (file.filename or "receipt").strip()
    if core.legacy._extension(filename) not in v5._RECEIPT_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Пришлите полный чек как PDF, JPG, JPEG, PNG или WEBP")
    data = await file.read(core._MAX_UPLOAD_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail="Пустой файл")
    if len(data) > core._MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Файл больше 20 МБ")

    try:
        check = await KaspiReceiptAnalyzer(settings).analyze(data, filename, file.content_type or "")
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Не удалось проверить фискальный чек Kaspi. Попробуйте загрузить полный PDF-чек ещё раз.",
        ) from exc

    created_at = await v5._order_created_at(order.id, user_key)
    issues = _strict_receipt_issues(check, order.amount_kzt, offered_at=created_at)
    if issues:
        raise HTTPException(
            status_code=422,
            detail="Чек не прошёл проверку Kaspi ОФД: " + "; ".join(issues[:6]),
        )

    receipt_hash = hashlib.sha256(data).hexdigest()
    fiscal_key = f"KASPI-OFD:{check.rnm}:{check.fp}"
    payload = _receipt_check_payload(check)

    if order.status == "pending_receipt":
        accepted = await payments.accept_document_receipt_precheck(
            order_id=order.id,
            user_key=user_key,
            receipt_hash=receipt_hash,
            transaction_id=fiscal_key,
            receipt_check=payload,
        )
        if not accepted:
            raise HTTPException(
                status_code=409,
                detail="Этот фискальный чек уже использовался или платёжный запрос уже обработан",
            )
    else:
        if not await v5._registered_receipt_belongs_to_order(order.id, receipt_hash):
            raise HTTPException(
                status_code=409,
                detail="Для этого старого заказа повторно загрузите исходный чек",
            )

    latest = await payments.get_document_order(order.id, user_key=user_key)
    if latest is None:
        raise HTTPException(status_code=409, detail="Не удалось восстановить платёжный запрос")
    if latest.status == "awaiting_admin":
        approved = await payments.decide_document_order(
            latest.id,
            approved=True,
            note="Kaspi OFD deterministic verification passed (v7)",
        )
        if not approved:
            raise HTTPException(status_code=409, detail="Статус оплаты изменился во время проверки; обновите экран")
        latest = await payments.get_document_order(latest.id, user_key=user_key)
        if latest is None:
            raise HTTPException(status_code=409, detail="Не удалось восстановить подтверждённую оплату")

    return {
        "ok": True,
        "payment_required": False,
        "generation_started": False,
        "payment": v5._payment_payload(latest),
        "message": "Фискальный чек подтверждён через Kaspi ОФД. Оплата принята автоматически.",
    }
