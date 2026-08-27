from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import File, Header, HTTPException, UploadFile

from korgan import miniapp_api_v4 as v4
from korgan import miniapp_document_payments as payments
from korgan.payment import ReceiptAnalyzer

app = v4.app
core = v4.core
settings = v4.settings
PARITY_REVISION = "2026-08-27.auto-payment-v5"
_RECEIPT_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}
_KZ_TZ = timezone(timedelta(hours=5))
_DATE_FORMATS = (
    "%d.%m.%Y %H:%M:%S",
    "%d.%m.%Y %H:%M",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d-%m-%Y %H:%M:%S",
    "%d-%m-%Y %H:%M",
)


def _drop(path: str, method: str) -> None:
    v4._drop_route(path, method)


# Replace only the document-payment surface. Consultation/payment quota and the
# legal runtime remain the existing Mini App implementation.
for _path, _method in (
    ("/miniapp/parity", "GET"),
    ("/miniapp/pricing", "GET"),
    ("/miniapp/documents/generate", "POST"),
    ("/miniapp/documents/payments/{order_id}/receipt", "POST"),
    ("/miniapp/documents/payments/{order_id}", "GET"),
):
    _drop(_path, _method)


def _payment_payload(order: payments.DocumentPaymentOrder) -> dict[str, Any]:
    return {
        "order_id": order.id,
        "case_id": order.case_id,
        "document_type": order.document_type,
        "amount_kzt": order.amount_kzt,
        "kaspi_url": settings.kaspi_payment_url,
        "status": order.status,
        "approval_required": False,
        "decision_note": order.decision_note,
        "receipt_accept": ["PDF", "JPG", "JPEG", "PNG", "WEBP"],
    }


def _normalize_recipient(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(ch for ch in normalized if ch.isalnum())


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
            for fmt in _DATE_FORMATS:
                try:
                    parsed = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
            if parsed is None:
                compact = re.sub(r"\s+", " ", text)
                for fmt in _DATE_FORMATS:
                    try:
                        parsed = datetime.strptime(compact, fmt)
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
        issues.append("документ не распознан как чек/квитанция Kaspi")
    if not bool(_check_value(check, "payment_successful", False)):
        issues.append("на чеке не подтверждён успешный платёж")
    amount = int(_check_value(check, "amount_kzt", 0) or 0)
    if amount != int(expected_amount):
        issues.append(f"сумма на чеке {amount} ₸ вместо {expected_amount} ₸")

    date_time = str(_check_value(check, "date_time", "") or "").strip()
    txid = str(_check_value(check, "receipt_or_transaction_id", "") or "").strip()
    recipient = str(_check_value(check, "merchant_or_recipient", "") or "").strip()
    suspicious = list(_check_value(check, "suspicious_signals", ()) or ())
    if not date_time:
        issues.append("на чеке не распознаны дата/время платежа")
    if not txid:
        issues.append("на чеке не распознан номер операции/чека")

    expected_recipient = str(settings.kaspi_payment_recipient or "").strip()
    if not expected_recipient:
        issues.append("получатель KORGAN не настроен")
    else:
        actual = _normalize_recipient(recipient)
        expected = _normalize_recipient(expected_recipient)
        if not actual:
            issues.append("на чеке не распознан получатель платежа")
        elif actual != expected:
            issues.append("получатель платежа не соответствует KORGAN")

    if date_time:
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
    if suspicious:
        issues.append("AI обнаружил признаки возможного изменения или аномалии чека")
    return issues


async def _order_created_at(order_id: int, user_key: str) -> datetime | None:
    return await payments._require_pool().fetchval(
        "SELECT created_at FROM korgan_miniapp_document_orders WHERE id=$1 AND user_key=$2",
        order_id,
        user_key,
    )


async def _registered_receipt_belongs_to_order(order_id: int, receipt_hash: str) -> bool:
    found = await payments._require_pool().fetchval(
        "SELECT order_id FROM korgan_miniapp_document_receipts WHERE receipt_hash=$1",
        receipt_hash,
    )
    return found is not None and int(found) == int(order_id)


async def _auto_approve_stored(order: payments.DocumentPaymentOrder, *, user_key: str) -> payments.DocumentPaymentOrder:
    if order.status != "awaiting_admin":
        return order
    created_at = await _order_created_at(order.id, user_key)
    issues = _strict_receipt_issues(order.receipt_check or {}, order.amount_kzt, offered_at=created_at)
    if issues:
        return order
    approved = await payments.decide_document_order(
        order.id,
        approved=True,
        note="AI receipt verification passed automatically (v5)",
    )
    if not approved:
        latest = await payments.get_document_order(order.id, user_key=user_key)
        return latest or order
    latest = await payments.get_document_order(order.id, user_key=user_key)
    return latest or order


async def _run_approved_document(
    order: payments.DocumentPaymentOrder,
    *,
    x_telegram_init_data: str,
) -> dict[str, Any]:
    if order.status != "approved":
        raise HTTPException(status_code=409, detail="Оплата ещё не прошла автоматическую проверку")

    identity = core.legacy._identity(x_telegram_init_data)
    state = await core.legacy._require_consent(identity)
    case = state["cases"].get(order.case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Дело для оплаченного документа не найдено")
    current_scope = v4._document_scope(case, order.document_type, order.language)
    if current_scope != order.case_fingerprint:
        raise HTTPException(
            status_code=409,
            detail="Оплата сохранена, но материалы дела изменились после неё. Повторно не платите; восстановите прежний состав дела или обратитесь в техподдержку.",
        )

    payload = core.GenerateRequest(
        case_id=order.case_id,
        document_type=order.document_type,
        language=order.language,
    )
    try:
        result = await core.generate_document(payload, x_telegram_init_data)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Оплата принята, но документ временно не удалось подготовить. Повторная оплата не нужна — нажмите повтор генерации.",
        ) from exc

    user_key = core.store.user_key(identity)
    if not await payments.consume_document_order(order.id, user_key=user_key):
        raise HTTPException(status_code=409, detail="Эта подтверждённая оплата уже использована")
    return {
        **result,
        "payment_required": False,
        "paid": True,
        "payment_order_id": order.id,
    }


@app.get("/miniapp/parity")
async def parity() -> dict[str, Any]:
    payload = await v4.parity()
    payload.update({
        "api_version": "1.0.0",
        "parity_revision": PARITY_REVISION,
        "document_manual_confirmation": False,
        "document_payment_admin_configured": False,
        "automatic_receipt_verification": True,
    })
    return payload


@app.get("/miniapp/pricing")
async def pricing(x_telegram_init_data: str = Header(default="")) -> dict[str, Any]:
    payload = await v4.pricing(x_telegram_init_data)
    payload["document_manual_confirmation"] = False
    payload["automatic_receipt_verification"] = True
    return payload


@app.post("/miniapp/documents/generate")
async def generate_document(
    payload: core.GenerateRequest,
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    if not settings.payments_enabled:
        return await core.generate_document(payload, x_telegram_init_data)
    if not settings.kaspi_payment_url.strip():
        raise HTTPException(status_code=503, detail="Kaspi-оплата временно не настроена. Документ не запущен.")

    identity = core.legacy._identity(x_telegram_init_data)
    state = await core.legacy._require_consent(identity)
    case = state["cases"].get(payload.case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    document_type = str(case.get("document_type") or payload.document_type or "claim")
    if document_type not in core._DOCUMENT_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported document type")
    if payload.document_type and payload.document_type != document_type:
        raise HTTPException(status_code=409, detail="Тип документа не соответствует активному делу")
    language = "kk" if str(case.get("language") or payload.language) == "kk" else "ru"
    if not core._case_context(case).strip():
        raise HTTPException(status_code=422, detail="Добавьте описание ситуации или загрузите материалы дела")

    user_key = core.store.user_key(identity)
    scope = v4._document_scope(case, document_type, language)
    order = await payments.get_scope_order(user_key=user_key, case_id=payload.case_id, case_fingerprint=scope)
    if order is None:
        order = await payments.create_document_order(
            user_key=user_key,
            case_id=payload.case_id,
            case_fingerprint=scope,
            document_type=document_type,
            language=language,
            amount_kzt=settings.document_price_kzt,
        )
    order = await _auto_approve_stored(order, user_key=user_key)
    if order.status != "approved":
        return {
            "payment_required": True,
            "generation_started": False,
            "payment": _payment_payload(order),
        }
    return await _run_approved_document(order, x_telegram_init_data=x_telegram_init_data)


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
        return {"ok": True, "payment_required": False, "payment": _payment_payload(order), "message": "Оплата уже проверена. Запускаю документ."}
    if order.status not in {"pending_receipt", "awaiting_admin"}:
        raise HTTPException(status_code=409, detail="Этот платёжный запрос уже закрыт")

    filename = (file.filename or "receipt").strip()
    if core.legacy._extension(filename) not in _RECEIPT_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Пришлите полный чек как PDF, JPG, JPEG, PNG или WEBP")
    data = await file.read(core._MAX_UPLOAD_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail="Пустой файл")
    if len(data) > core._MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Файл больше 20 МБ")

    try:
        check = await ReceiptAnalyzer(settings).analyze(data, filename, file.content_type or "")
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Не удалось проверить чек. Документ не разблокирован.") from exc

    created_at = await _order_created_at(order.id, user_key)
    issues = _strict_receipt_issues(check, order.amount_kzt, offered_at=created_at)
    if issues:
        raise HTTPException(status_code=422, detail="Чек не прошёл автоматическую проверку: " + "; ".join(issues[:6]))

    receipt_hash = hashlib.sha256(data).hexdigest()
    if order.status == "pending_receipt":
        accepted = await payments.accept_document_receipt_precheck(
            order_id=order.id,
            user_key=user_key,
            receipt_hash=receipt_hash,
            transaction_id=str(check.receipt_or_transaction_id or ""),
            receipt_check=v4._receipt_check_payload(check),
        )
        if not accepted:
            raise HTTPException(status_code=409, detail="Этот чек/номер операции уже использовался или запрос уже обработан")
    else:
        # Legacy v4 order: the receipt is already registered to this same order.
        if not await _registered_receipt_belongs_to_order(order.id, receipt_hash):
            raise HTTPException(status_code=409, detail="Этот старый платёж ожидает повторной загрузки именно исходного чека")

    latest = await payments.get_document_order(order.id, user_key=user_key)
    if latest is None:
        raise HTTPException(status_code=409, detail="Не удалось восстановить платёжный запрос")
    if latest.status == "awaiting_admin":
        approved = await payments.decide_document_order(
            latest.id,
            approved=True,
            note="AI receipt verification passed automatically (v5)",
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
        "payment": _payment_payload(latest),
        "message": "KORGAN AI проверил чек. Оплата подтверждена автоматически — запускаю подготовку документа.",
    }


@app.get("/miniapp/documents/payments/{order_id}")
async def document_payment_status(
    order_id: int,
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    identity = core.legacy._identity(x_telegram_init_data)
    await core.legacy._require_consent(identity)
    user_key = core.store.user_key(identity)
    order = await payments.get_document_order(order_id, user_key=user_key)
    if order is None:
        raise HTTPException(status_code=404, detail="Платёжный запрос не найден")
    order = await _auto_approve_stored(order, user_key=user_key)
    return {"payment": _payment_payload(order)}


@app.post("/miniapp/documents/payments/{order_id}/retry")
async def retry_paid_document(
    order_id: int,
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    identity = core.legacy._identity(x_telegram_init_data)
    await core.legacy._require_consent(identity)
    user_key = core.store.user_key(identity)
    order = await payments.get_document_order(order_id, user_key=user_key)
    if order is None:
        raise HTTPException(status_code=404, detail="Платёжный запрос не найден")
    order = await _auto_approve_stored(order, user_key=user_key)
    return await _run_approved_document(order, x_telegram_init_data=x_telegram_init_data)
