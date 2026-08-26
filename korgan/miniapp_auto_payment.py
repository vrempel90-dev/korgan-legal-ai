from __future__ import annotations

import logging
from typing import Any

from fastapi import File, Header, HTTPException, UploadFile

from korgan import miniapp_api_v4 as runtime
from korgan.consultation_quota import receipt_fingerprint
from korgan.miniapp_document_payments import (
    accept_document_receipt_ai_verified,
    consume_document_order,
    get_document_order,
)
from korgan.payment import ReceiptAnalyzer, receipt_hard_issues

LOGGER = logging.getLogger(__name__)

app = runtime.app
core = runtime.core
settings = runtime.settings


def _drop_route(path: str, method: str) -> None:
    wanted = method.upper()
    app.router.routes = [
        route
        for route in app.router.routes
        if not (
            getattr(route, "path", None) == path
            and wanted in (getattr(route, "methods", set()) or set())
        )
    ]


# v4 remains the compatibility/base runtime. These three routes replace only the
# document-payment policy for new Mini App requests. Legacy admin endpoints stay
# available for orders already left in awaiting_admin by older deployments.
_drop_route("/miniapp/parity", "GET")
_drop_route("/miniapp/pricing", "GET")
_drop_route("/miniapp/documents/payments/{order_id}/receipt", "POST")


@app.get("/miniapp/parity")
async def parity() -> dict[str, Any]:
    payload = dict(await runtime.parity())
    payload.update(
        {
            "parity_revision": "2026-08-26.2-auto-payment",
            "document_manual_confirmation": False,
            "document_ai_receipt_verification": True,
            "document_auto_generation_after_receipt": True,
        }
    )
    return payload


@app.get("/miniapp/pricing")
async def pricing(x_telegram_init_data: str = Header(default="")) -> dict[str, Any]:
    payload = dict(await runtime.pricing(x_telegram_init_data))
    payload.update(
        {
            "document_manual_confirmation": False,
            "document_ai_receipt_verification": True,
            "document_auto_generation_after_receipt": True,
        }
    )
    return payload


@app.post("/miniapp/documents/payments/{order_id}/receipt")
async def document_payment_receipt(
    order_id: int,
    file: UploadFile = File(...),
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    """Verify one receipt and immediately generate the paid document.

    No legal research or Word generation runs before this endpoint has accepted
    the receipt. The uploaded receipt is checked by the strict KORGAN AI verifier,
    then fingerprint/transaction-id uniqueness and immutable case scope are
    enforced before the payment order is atomically marked approved.
    """
    identity = core.legacy._identity(x_telegram_init_data)
    state = await core.legacy._require_consent(identity)
    user_key = core.store.user_key(identity)
    order = await get_document_order(order_id, user_key=user_key)
    if order is None:
        raise HTTPException(status_code=404, detail="Платёжный запрос не найден")
    if order.status != "pending_receipt":
        if order.status == "approved":
            raise HTTPException(
                status_code=409,
                detail="Оплата уже проверена AI. Повторно платить и загружать чек не нужно — запустите подготовку документа ещё раз.",
            )
        raise HTTPException(status_code=409, detail="Этот платёжный запрос уже обработан или устарел")

    case = state.get("cases", {}).get(order.case_id)
    if not case:
        raise HTTPException(status_code=409, detail="Дело для этой оплаты больше недоступно. Документ не запущен.")
    current_scope = runtime._document_scope(case, order.document_type, order.language)
    if current_scope != order.case_fingerprint:
        LOGGER.warning("MINIAPP_PAYMENT_SCOPE_REJECTED order=%s case=%s", order.id, order.case_id)
        raise HTTPException(
            status_code=409,
            detail="Материалы дела изменились после открытия оплаты. Старый чек не может разблокировать изменённый документ.",
        )

    filename = (file.filename or "receipt").strip()
    if core.legacy._extension(filename) not in runtime._RECEIPT_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Пришлите полный чек как PDF, JPG, JPEG, PNG или WEBP")
    data = await file.read(core._MAX_UPLOAD_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail="Пустой файл")
    if len(data) > core._MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Файл больше 20 МБ")

    try:
        check = await ReceiptAnalyzer(settings).analyze(data, filename, file.content_type or "")
    except Exception as exc:
        LOGGER.exception("MINIAPP_PAYMENT_AI_FAILED order=%s", order.id)
        raise HTTPException(
            status_code=502,
            detail="Не удалось выполнить обязательную AI-проверку чека. Документ не разблокирован.",
        ) from exc

    issues = receipt_hard_issues(check, order.amount_kzt)
    if issues:
        LOGGER.warning("MINIAPP_PAYMENT_AI_REJECTED order=%s issues=%s", order.id, issues[:6])
        raise HTTPException(
            status_code=422,
            detail="Чек не прошёл автоматическую проверку: " + "; ".join(issues[:6]),
        )

    accepted = await accept_document_receipt_ai_verified(
        order_id=order.id,
        user_key=user_key,
        receipt_hash=receipt_fingerprint(data),
        transaction_id=check.receipt_or_transaction_id,
        receipt_check=runtime._receipt_check_payload(check),
    )
    if not accepted:
        raise HTTPException(
            status_code=409,
            detail="Этот чек/номер операции уже использовался либо платёжный запрос уже был обработан",
        )

    LOGGER.info(
        "MINIAPP_PAYMENT_AI_VERIFIED order=%s case=%s kind=%s transaction=%s amount=%s",
        order.id,
        order.case_id,
        order.document_type,
        check.receipt_or_transaction_id[:80],
        check.amount_kzt,
    )

    payload = core.GenerateRequest(
        case_id=order.case_id,
        document_type=order.document_type,
        language=order.language,
    )
    try:
        # Call the underlying legal generator directly: the order has already
        # passed payment verification above. v4's route-level payment wrapper is
        # intentionally bypassed so there is no human-confirmation stop.
        result = await core.generate_document(payload, x_telegram_init_data)
    except Exception as exc:
        # Keep status=approved. The client can retry generation without another
        # payment; the receipt remains uniquely reserved and cannot be replayed.
        LOGGER.exception("MINIAPP_PAID_GENERATION_FAILED order=%s case=%s", order.id, order.case_id)
        raise HTTPException(
            status_code=503,
            detail="KORGAN AI уже проверил оплату, но документ временно не сформирован. Повторная оплата не нужна — повторите подготовку документа.",
        ) from exc

    if not await consume_document_order(order.id, user_key=user_key):
        LOGGER.error("MINIAPP_PAYMENT_CONSUME_FAILED order=%s case=%s", order.id, order.case_id)
        raise HTTPException(
            status_code=409,
            detail="Оплата проверена, но платёжный запрос уже был использован. Документ повторно не выдан.",
        )

    LOGGER.info("MINIAPP_PAID_DOCUMENT_DELIVERED order=%s case=%s", order.id, order.case_id)
    return {
        **result,
        "payment_required": False,
        "paid": True,
        "payment_order_id": order.id,
        "ai_receipt_verified": True,
    }
