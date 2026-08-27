from __future__ import annotations

from typing import Any

from fastapi import Header, HTTPException
from pydantic import BaseModel, Field

from korgan import miniapp_api_v5 as runtime
from korgan.consultation_quota import ConsultationOrder, get_consultation_order
from korgan.kaspi_ofd import (
    KaspiFiscalReceipt,
    KaspiOFDVerificationError,
    fetch_kaspi_ofd_receipt,
    fiscal_receipt_issues,
)
from korgan.miniapp_consultation_payment_parity import (
    accept_ai_verified_consultation_receipt,
    get_consultation_order_created_at,
)
from korgan.miniapp_document_payments import DocumentPaymentOrder, consume_document_order, get_document_order
from korgan.miniapp_payment_parity import (
    accept_ai_verified_document_receipt,
    get_document_order_created_at,
)

core = runtime.core
app = runtime.app
settings = runtime.settings
service = runtime.service
PARITY_REVISION = "2026-08-27.3-kaspi-ofd"


class FiscalQrRequest(BaseModel):
    qr_url: str = Field(min_length=20, max_length=2048)


def _consultation_payment_payload(order: ConsultationOrder) -> dict[str, Any]:
    return {
        "order_id": order.id,
        "amount_kzt": order.amount_kzt,
        "kaspi_url": settings.kaspi_payment_url,
        "status": order.status,
        "approval_required": False,
        "ai_verification": False,
        "ofd_verification": True,
        "receipt_input": "fiscal_qr_url",
        "receipt_host": "receipt.kaspi.kz",
        "can_retry": order.status == "paid",
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
        "ai_verification": False,
        "ofd_verification": True,
        "receipt_input": "fiscal_qr_url",
        "receipt_host": "receipt.kaspi.kz",
        "decision_note": order.decision_note,
    }


def _receipt_check_payload(receipt: KaspiFiscalReceipt) -> dict[str, Any]:
    return {
        "verification_source": "kaspi_ofd",
        "canonical_url": receipt.canonical_url,
        "successful": receipt.successful,
        "amount_kzt": receipt.amount_kzt,
        "date_time": receipt.sale_datetime,
        "merchant_or_recipient": receipt.seller_name,
        "seller_bin": receipt.seller_bin,
        "receipt_or_transaction_id": receipt.transaction_id,
        "receipt_number": receipt.receipt_number,
        "rnm": receipt.rnm,
        "fp": receipt.fp,
        "ofd": receipt.ofd_name,
        "payment_method": receipt.payment_method,
    }


def _require_payment_configuration() -> None:
    if not settings.kaspi_payment_url.strip():
        raise HTTPException(status_code=503, detail="Оплата временно недоступна: Kaspi не настроен.")
    if not (settings.kaspi_payment_bin.strip() or settings.kaspi_payment_recipient.strip()):
        raise HTTPException(
            status_code=503,
            detail="Оплата временно недоступна: получатель KORGAN не настроен. Документ остаётся заблокирован.",
        )


async def _fetch_and_validate(
    qr_url: str,
    *,
    amount_kzt: int,
    offered_at: Any,
) -> KaspiFiscalReceipt:
    try:
        receipt = await fetch_kaspi_ofd_receipt(qr_url)
    except KaspiOFDVerificationError as exc:
        raise HTTPException(status_code=422, detail=f"Фискальный QR не подтверждён Kaspi ОФД: {exc}") from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Kaspi ОФД временно недоступен. Повторно платить не нужно — отправьте ту же QR-ссылку позже.",
        ) from exc

    issues = fiscal_receipt_issues(
        receipt,
        amount_kzt,
        expected_recipient=settings.kaspi_payment_recipient,
        expected_bin=settings.kaspi_payment_bin,
        offered_at=offered_at,
    )
    if issues:
        raise HTTPException(
            status_code=422,
            detail="Фискальный чек не прошёл проверку Kaspi ОФД: " + "; ".join(issues[:6]),
        )
    return receipt


async def _generate_verified_order(
    *,
    identity: str,
    order: DocumentPaymentOrder,
    init_data: str,
) -> dict[str, Any]:
    if order.status != "approved":
        raise HTTPException(status_code=409, detail="Оплата этого документа ещё не подтверждена Kaspi ОФД")

    state = await core.legacy._require_consent(identity)
    case = state["cases"].get(order.case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    current_scope = runtime.runtime._document_scope(case, order.document_type, order.language)
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
            detail="Фискальный чек уже принят и оплата подтверждена Kaspi ОФД, но документ временно не сформирован. Повторно платить не нужно — запустите повтор.",
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
            "payment_verification": "kaspi_ofd",
        }

    return {
        **result,
        "payment_required": False,
        "paid": True,
        "payment_order_id": order.id,
        "payment_verification": "kaspi_ofd",
    }


# Existing v5 route functions look these helpers up in their module globals at
# request time. Replacing them keeps all case/generation/order behaviour intact
# while changing only the payment-verification contract.
runtime._consultation_payment_payload = _consultation_payment_payload
runtime._document_payment_payload = _document_payment_payload
runtime._require_payment_configuration = _require_payment_configuration
runtime._generate_verified_order = _generate_verified_order

for _path, _method in (
    ("/miniapp/parity", "GET"),
    ("/miniapp/pricing", "GET"),
    ("/miniapp/consultation/payments/{order_id}/receipt", "POST"),
    ("/miniapp/documents/payments/{order_id}/receipt", "POST"),
):
    runtime.runtime._drop_route(_path, _method)


@app.get("/miniapp/parity")
async def parity() -> dict[str, Any]:
    inner = getattr(service, "inner", None)
    stable = getattr(inner, "stable", None)
    return {
        "status": "ok",
        "api_version": "1.1.0",
        "parity_revision": PARITY_REVISION,
        "legal_runtime": "strict_bot",
        "service_outer": type(service).__name__,
        "service_claim_mux": type(inner).__name__ if inner is not None else "",
        "service_stable": type(stable).__name__ if stable is not None else "",
        "claim_pipeline_v2_mode": runtime.runtime.runtime.claim_pipeline_v2_mode(),
        "word_quality_target": "10/10",
        "preliminary_fallback": True,
        "official_corpus_refresh": bool(runtime.runtime.runtime._corpus_task is not None),
        "consultation_limit_enabled": bool(settings.consultation_limit_enabled),
        "free_consultations_per_day": int(settings.free_consultations_per_day),
        "consultation_price_kzt": int(settings.consultation_price_kzt),
        "consultation_ai_receipt_verification": False,
        "consultation_ofd_receipt_verification": True,
        "document_payments_enabled": bool(settings.payments_enabled),
        "document_price_kzt": int(settings.document_price_kzt),
        "document_manual_confirmation": False,
        "document_ai_receipt_verification": False,
        "document_ofd_receipt_verification": True,
        "payment_recipient_configured": bool(settings.kaspi_payment_bin.strip() or settings.kaspi_payment_recipient.strip()),
        "payment_bin_configured": bool(settings.kaspi_payment_bin.strip()),
        "receipt_input": "fiscal_qr_url",
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
        "consultation_ai_receipt_verification": False,
        "consultation_ofd_receipt_verification": True,
        "document_price_kzt": int(settings.document_price_kzt),
        "document_payments_enabled": bool(settings.payments_enabled),
        "document_manual_confirmation": False,
        "document_ai_receipt_verification": False,
        "document_ofd_receipt_verification": True,
        "receipt_input": "fiscal_qr_url",
        "kaspi_url": settings.kaspi_payment_url if settings.consultation_limit_enabled or settings.payments_enabled else "",
    }


@app.post("/miniapp/consultation/payments/{order_id}/receipt")
async def consultation_payment_receipt(
    order_id: int,
    payload: FiscalQrRequest,
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    _require_payment_configuration()
    identity = core.legacy._identity(x_telegram_init_data)
    state = await core.legacy._require_consent(identity)
    user_id = runtime.runtime._quota_user_id(identity)
    order = await get_consultation_order(order_id, user_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Платёжный запрос консультации не найден")
    if order.status == "paid":
        return await runtime.runtime._answer_paid_order(identity=identity, state=state, order=order)
    if order.status != "pending":
        raise HTTPException(status_code=409, detail="Этот платёжный запрос уже обработан или использован")

    offered_at = await get_consultation_order_created_at(order.id, user_id=user_id)
    receipt = await _fetch_and_validate(payload.qr_url, amount_kzt=order.amount_kzt, offered_at=offered_at)

    try:
        accepted = await accept_ai_verified_consultation_receipt(
            order_id=order.id,
            user_id=user_id,
            receipt_hash=receipt.receipt_fingerprint,
            transaction_id=receipt.transaction_id,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Не удалось безопасно закрепить фискальный чек. Консультация остаётся заблокирована. Повторно платить не нужно.",
        ) from exc
    if not accepted:
        raise HTTPException(status_code=409, detail="Этот фискальный чек уже использовался для другого платёжного запроса")

    paid = await get_consultation_order(order.id, user_id)
    if paid is None or paid.status != "paid":
        raise HTTPException(status_code=503, detail="Оплата проверена, но статус не удалось сохранить. Повторно платить не нужно.")
    return await runtime.runtime._answer_paid_order(identity=identity, state=state, order=paid)


@app.post("/miniapp/documents/payments/{order_id}/receipt")
async def document_payment_receipt(
    order_id: int,
    payload: FiscalQrRequest,
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

    offered_at = await get_document_order_created_at(order.id, user_key=user_key)
    receipt = await _fetch_and_validate(payload.qr_url, amount_kzt=order.amount_kzt, offered_at=offered_at)

    try:
        accepted = await accept_ai_verified_document_receipt(
            order_id=order.id,
            user_key=user_key,
            receipt_hash=receipt.receipt_fingerprint,
            transaction_id=receipt.transaction_id,
            receipt_check=_receipt_check_payload(receipt),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Не удалось безопасно закрепить фискальный чек. Документ остаётся заблокирован. Повторно платить не нужно.",
        ) from exc
    if not accepted:
        raise HTTPException(status_code=409, detail="Этот фискальный чек уже использовался для другого платёжного запроса")

    verified = await get_document_order(order.id, user_key=user_key)
    if verified is None or verified.status != "approved":
        raise HTTPException(status_code=503, detail="Оплата проверена, но статус не удалось сохранить. Повторно платить не нужно.")
    return await _generate_verified_order(identity=identity, order=verified, init_data=x_telegram_init_data)
