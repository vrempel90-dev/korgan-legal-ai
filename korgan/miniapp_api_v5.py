from __future__ import annotations

from typing import Any

from fastapi import File, Header, HTTPException, Request, UploadFile

from korgan import miniapp_api_v4 as runtime
from korgan.consultation_quota import ConsultationOrder, get_consultation_order, receipt_fingerprint
from korgan.miniapp_consultation_payment_parity import (
    accept_ai_verified_consultation_receipt,
    get_consultation_order_created_at,
    get_latest_open_consultation_order,
)
from korgan.miniapp_document_payments import (
    DocumentPaymentOrder,
    consume_document_order,
    create_document_order,
    get_document_order,
    get_scope_order,
)
from korgan.miniapp_payment_parity import (
    accept_ai_verified_document_receipt,
    get_document_order_created_at,
)
from korgan.payment import ReceiptAnalyzer, receipt_hard_issues

core = runtime.core
app = runtime.app
settings = runtime.settings
service = runtime.service
PARITY_REVISION = "2026-08-27.2"
_RECEIPT_EXTENSIONS = runtime._RECEIPT_EXTENSIONS

# v5 changes only the dedicated Mini App HTTP contract. The Telegram AI agent,
# polling runtime, routers and its production branch/service are not modified.
for _path, _method in (
    ("/miniapp/parity", "GET"),
    ("/miniapp/pricing", "GET"),
    ("/miniapp/consultation/payments/{order_id}/receipt", "POST"),
    ("/miniapp/documents/generate", "POST"),
    ("/miniapp/documents/payments/{order_id}/receipt", "POST"),
    ("/miniapp/documents/payments/{order_id}", "GET"),
    ("/miniapp/admin/document-payments", "GET"),
    ("/miniapp/admin/document-payments/{order_id}/decision", "POST"),
):
    runtime._drop_route(_path, _method)


@app.middleware("http")
async def serialize_miniapp_user_requests(request: Request, call_next):
    """Prevent stale encrypted-state snapshots from overwriting newer ones.

    The Mini App API is a separate Railway process from the Telegram agent. A
    per-user lock is held across each Mini App request, including long AI work,
    so state load/mutate/save sequences for one identity cannot race each other.
    """
    if not request.url.path.startswith("/miniapp/"):
        return await call_next(request)
    raw = request.headers.get("x-telegram-init-data", "")
    if not raw:
        return await call_next(request)
    try:
        identity = core.legacy._identity(raw)
    except Exception:
        # The endpoint remains responsible for returning the canonical auth
        # error. Invalid requests never receive a trusted per-user lock key.
        return await call_next(request)
    lock = await core.store.user_lock(identity)
    async with lock:
        return await call_next(request)


def _consultation_payment_payload(order: ConsultationOrder) -> dict[str, Any]:
    return {
        "order_id": order.id,
        "amount_kzt": order.amount_kzt,
        "kaspi_url": settings.kaspi_payment_url,
        "status": order.status,
        "approval_required": False,
        "ai_verification": True,
        "can_retry": order.status == "paid",
        "receipt_accept": ["PDF", "JPG", "JPEG", "PNG", "WEBP"],
    }


def _document_payment_payload(order: DocumentPaymentOrder) -> dict[str, Any]:
    return {
        "order_id": order.id,
        "case_id": order.case_id,
        "document_type": order.document_type,
        "amount_kzt": order.amount_kzt,
        "kaspi_url": settings.kaspi_payment_url,
        "status": order.status,
        "approval_required": False,
        "ai_verification": True,
        "decision_note": order.decision_note,
        "receipt_accept": ["PDF", "JPG", "JPEG", "PNG", "WEBP"],
    }


def _receipt_check_payload(check: Any) -> dict[str, Any]:
    return {
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


def _require_payment_configuration() -> None:
    if not settings.kaspi_payment_url.strip():
        raise HTTPException(status_code=503, detail="Оплата временно недоступна: Kaspi не настроен.")
    if not settings.kaspi_payment_recipient.strip():
        raise HTTPException(
            status_code=503,
            detail="Оплата временно недоступна: получатель KORGAN не настроен. Доступ не разблокирован.",
        )


async def _resolve_order(
    *,
    identity: str,
    case: dict[str, Any],
    case_id: str,
    document_type: str,
    language: str,
) -> DocumentPaymentOrder:
    user_key = core.store.user_key(identity)
    scope = runtime._document_scope(case, document_type, language)
    order = await get_scope_order(user_key=user_key, case_id=case_id, case_fingerprint=scope)
    if order is None:
        order = await create_document_order(
            user_key=user_key,
            case_id=case_id,
            case_fingerprint=scope,
            document_type=document_type,
            language=language,
            amount_kzt=settings.document_price_kzt,
        )
    return order


async def _generate_verified_order(
    *,
    identity: str,
    order: DocumentPaymentOrder,
    init_data: str,
) -> dict[str, Any]:
    if order.status != "approved":
        raise HTTPException(status_code=409, detail="Оплата этого документа ещё не прошла AI-проверку")

    state = await core.legacy._require_consent(identity)
    case = state["cases"].get(order.case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    current_scope = runtime._document_scope(case, order.document_type, order.language)
    if current_scope != order.case_fingerprint:
        raise HTTPException(
            status_code=409,
            detail="Материалы дела изменились после оплаты. Оплаченный запрос сохранён, но для нового состава материалов нужна новая заявка.",
        )

    payload = core.GenerateRequest(
        case_id=order.case_id,
        document_type=order.document_type,
        language=order.language,
    )
    try:
        result = await core.generate_document(payload, init_data)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Чек уже принят и оплата подтверждена AI, но документ временно не сформирован. Повторно платить не нужно — запустите повтор.",
        ) from exc

    if not await consume_document_order(order.id, user_key=order.user_key):
        try:
            existing = await core.get_document(order.case_id, init_data)
        except Exception as exc:
            raise HTTPException(status_code=409, detail="Оплаченная генерация уже была использована") from exc
        return {
            **existing,
            "payment_required": False,
            "paid": True,
            "payment_order_id": order.id,
        }

    return {
        **result,
        "payment_required": False,
        "paid": True,
        "payment_order_id": order.id,
    }


@app.get("/miniapp/parity")
async def parity() -> dict[str, Any]:
    inner = getattr(service, "inner", None)
    stable = getattr(inner, "stable", None)
    return {
        "status": "ok",
        "api_version": "1.0.0",
        "parity_revision": PARITY_REVISION,
        "legal_runtime": "strict_bot",
        "service_outer": type(service).__name__,
        "service_claim_mux": type(inner).__name__ if inner is not None else "",
        "service_stable": type(stable).__name__ if stable is not None else "",
        "claim_pipeline_v2_mode": runtime.runtime.claim_pipeline_v2_mode(),
        "word_quality_target": "10/10",
        "preliminary_fallback": True,
        "official_corpus_refresh": bool(runtime.runtime._corpus_task is not None),
        "consultation_limit_enabled": bool(settings.consultation_limit_enabled),
        "free_consultations_per_day": int(settings.free_consultations_per_day),
        "consultation_price_kzt": int(settings.consultation_price_kzt),
        "consultation_ai_receipt_verification": True,
        "document_payments_enabled": bool(settings.payments_enabled),
        "document_price_kzt": int(settings.document_price_kzt),
        "document_manual_confirmation": False,
        "document_ai_receipt_verification": True,
        "payment_recipient_configured": bool(settings.kaspi_payment_recipient.strip()),
        "document_types": sorted(core._DOCUMENT_TYPES),
    }


@app.get("/miniapp/pricing")
async def pricing(x_telegram_init_data: str = Header(default="")) -> dict[str, Any]:
    identity = core.legacy._identity(x_telegram_init_data)
    await core.legacy._require_consent(identity)
    return {
        "consultation_limit_enabled": bool(settings.consultation_limit_enabled),
        "free_consultations_per_day": int(settings.free_consultations_per_day),
        "consultation_price_kzt": int(settings.consultation_price_kzt),
        "consultation_ai_receipt_verification": True,
        "document_price_kzt": int(settings.document_price_kzt),
        "document_payments_enabled": bool(settings.payments_enabled),
        "document_manual_confirmation": False,
        "document_ai_receipt_verification": True,
        "kaspi_url": settings.kaspi_payment_url if settings.consultation_limit_enabled or settings.payments_enabled else "",
    }


@app.get("/miniapp/consultation/payment/pending")
async def pending_consultation_payment(
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    identity = core.legacy._identity(x_telegram_init_data)
    await core.legacy._require_consent(identity)
    if not settings.consultation_limit_enabled:
        return {"payment_required": False, "payment": None}
    order = await get_latest_open_consultation_order(runtime._quota_user_id(identity))
    if order is None:
        return {"payment_required": False, "payment": None}
    return {"payment_required": True, "payment": _consultation_payment_payload(order)}


@app.post("/miniapp/consultation/payments/{order_id}/receipt")
async def consultation_payment_receipt(
    order_id: int,
    file: UploadFile = File(...),
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    _require_payment_configuration()
    identity = core.legacy._identity(x_telegram_init_data)
    state = await core.legacy._require_consent(identity)
    user_id = runtime._quota_user_id(identity)
    order = await get_consultation_order(order_id, user_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Платёжный запрос консультации не найден")
    if order.status == "paid":
        return await runtime._answer_paid_order(identity=identity, state=state, order=order)
    if order.status != "pending":
        raise HTTPException(status_code=409, detail="Этот платёжный запрос уже обработан или использован")

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
        raise HTTPException(
            status_code=502,
            detail="Не удалось автоматически проверить чек. Консультация не разблокирована, повторно платить не нужно.",
        ) from exc

    offered_at = await get_consultation_order_created_at(order.id, user_id=user_id)
    issues = receipt_hard_issues(
        check,
        order.amount_kzt,
        expected_recipient=settings.kaspi_payment_recipient,
        offered_at=offered_at,
    )
    if issues:
        raise HTTPException(
            status_code=422,
            detail="Чек не прошёл автоматическую AI-проверку: " + "; ".join(issues[:6]),
        )

    try:
        accepted = await accept_ai_verified_consultation_receipt(
            order_id=order.id,
            user_id=user_id,
            receipt_hash=receipt_fingerprint(data),
            transaction_id=check.receipt_or_transaction_id,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Автоматическая проверка оплаты временно недоступна. Консультация остаётся заблокирована. Не платите повторно — загрузите этот же чек позже.",
        ) from exc
    if not accepted:
        raise HTTPException(status_code=409, detail="Этот чек/номер операции уже использовался для другого платёжного запроса")

    paid = await get_consultation_order(order.id, user_id)
    if paid is None or paid.status != "paid":
        raise HTTPException(status_code=503, detail="Оплата проверена, но статус не удалось сохранить. Повторно платить не нужно.")
    return await runtime._answer_paid_order(identity=identity, state=state, order=paid)


@app.post("/miniapp/documents/generate")
async def generate_document(
    payload: core.GenerateRequest,
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    if not settings.payments_enabled:
        return await core.generate_document(payload, x_telegram_init_data)

    _require_payment_configuration()
    identity = core.legacy._identity(x_telegram_init_data)
    state = await core.legacy._require_consent(identity)
    case = state["cases"].get(payload.case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    document_type = str(case.get("document_type") or payload.document_type or "claim")
    if document_type not in core._DOCUMENT_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported document type")
    language = "kk" if str(case.get("language") or payload.language) == "kk" else "ru"
    if not core._case_context(case).strip():
        raise HTTPException(status_code=422, detail="Добавьте описание ситуации или загрузите материалы дела")

    order = await _resolve_order(
        identity=identity,
        case=case,
        case_id=payload.case_id,
        document_type=document_type,
        language=language,
    )
    if order.status != "approved":
        return {
            "payment_required": True,
            "generation_started": False,
            "payment": _document_payment_payload(order),
        }
    return await _generate_verified_order(identity=identity, order=order, init_data=x_telegram_init_data)


@app.post("/miniapp/documents/payments/{order_id}/receipt")
async def document_payment_receipt(
    order_id: int,
    file: UploadFile = File(...),
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    _require_payment_configuration()
    identity = core.legacy._identity(x_telegram_init_data)
    await core.legacy._require_consent(identity)
    user_key = core.store.user_key(identity)
    order = await get_document_order(order_id, user_key=user_key)
    if order is None:
        raise HTTPException(status_code=404, detail="Платёжный запрос не найден")
    if order.status == "approved":
        return await _generate_verified_order(identity=identity, order=order, init_data=x_telegram_init_data)
    if order.status not in {"pending_receipt", "awaiting_admin"}:
        raise HTTPException(status_code=409, detail="Этот платёжный запрос уже обработан или использован")

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
        raise HTTPException(
            status_code=502,
            detail="Не удалось автоматически проверить чек. Документ не разблокирован, повторно платить не нужно.",
        ) from exc

    offered_at = await get_document_order_created_at(order.id, user_key=user_key)
    issues = receipt_hard_issues(
        check,
        order.amount_kzt,
        expected_recipient=settings.kaspi_payment_recipient,
        offered_at=offered_at,
    )
    if issues:
        raise HTTPException(
            status_code=422,
            detail="Чек не прошёл автоматическую AI-проверку: " + "; ".join(issues[:6]),
        )

    try:
        accepted = await accept_ai_verified_document_receipt(
            order_id=order.id,
            user_key=user_key,
            receipt_hash=receipt_fingerprint(data),
            transaction_id=check.receipt_or_transaction_id,
            receipt_check=_receipt_check_payload(check),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Автоматическая проверка оплаты временно недоступна. Документ остаётся заблокирован. Не платите повторно — загрузите этот же чек позже.",
        ) from exc
    if not accepted:
        raise HTTPException(status_code=409, detail="Этот чек/номер операции уже использовался для другого платёжного запроса")

    verified = await get_document_order(order.id, user_key=user_key)
    if verified is None or verified.status != "approved":
        raise HTTPException(status_code=503, detail="Оплата проверена, но статус не удалось сохранить. Повторно платить не нужно.")

    return await _generate_verified_order(identity=identity, order=verified, init_data=x_telegram_init_data)


@app.post("/miniapp/documents/payments/{order_id}/retry")
async def retry_paid_document(
    order_id: int,
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    identity = core.legacy._identity(x_telegram_init_data)
    await core.legacy._require_consent(identity)
    order = await get_document_order(order_id, user_key=core.store.user_key(identity))
    if order is None:
        raise HTTPException(status_code=404, detail="Платёжный запрос не найден")
    return await _generate_verified_order(identity=identity, order=order, init_data=x_telegram_init_data)


@app.get("/miniapp/documents/payments/{order_id}")
async def document_payment_status(
    order_id: int,
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    identity = core.legacy._identity(x_telegram_init_data)
    await core.legacy._require_consent(identity)
    order = await get_document_order(order_id, user_key=core.store.user_key(identity))
    if order is None:
        raise HTTPException(status_code=404, detail="Платёжный запрос не найден")
    return {"payment": _document_payment_payload(order)}
