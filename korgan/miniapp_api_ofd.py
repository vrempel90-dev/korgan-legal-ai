from __future__ import annotations

import hashlib
import re
from typing import Any, Awaitable, Callable, TypeVar

from fastapi import Header, HTTPException
from pydantic import BaseModel, Field

from korgan import consultation_quota as consultation_store
from korgan import miniapp_api_v5 as v5
from korgan import miniapp_document_payments as document_store
from korgan.kaspi_ofd import (
    KaspiFiscalReceipt,
    KaspiOFDVerificationError,
    fetch_kaspi_ofd_receipt,
    fiscal_receipt_issues,
)

app = v5.app
core = v5.core
settings = v5.settings
v4 = v5.v4
PARITY_REVISION = "2026-08-30.kaspi-ofd-agent-parity-v2"
_T = TypeVar("_T")


class FiscalReceiptUrl(BaseModel):
    receipt_url: str = Field(min_length=10, max_length=2048)


def _configured_values(value: str) -> set[str]:
    return {part.strip() for part in re.split(r"[|;,]+", str(value or "")) if part.strip()}


def _lock_key(namespace: str, order_id: int) -> int:
    digest = hashlib.sha256(f"{namespace}:{int(order_id)}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)


async def _locked(pool: Any, key: int, operation: Callable[[], Awaitable[_T]]) -> _T:
    # Backend idempotency guard. It prevents double legal generation/delivery if
    # a Telegram WebView sends two requests or the user taps twice quickly.
    async with pool.acquire() as connection:
        await connection.execute("SELECT pg_advisory_lock($1)", key)
        try:
            return await operation()
        finally:
            await connection.execute("SELECT pg_advisory_unlock($1)", key)


def _fiscal_payload(receipt: KaspiFiscalReceipt) -> dict[str, Any]:
    return {
        "readable": True,
        "looks_like_kaspi": True,
        "payment_successful": bool(receipt.successful),
        "amount_kzt": int(receipt.amount_kzt),
        "date_time": receipt.sale_datetime,
        "merchant_or_recipient": receipt.seller_name,
        "payer": "",
        "receipt_or_transaction_id": receipt.receipt_number,
        "rnm": receipt.rnm,
        "fp": receipt.fp,
        "seller_bin": receipt.seller_bin,
        "official_verified": True,
        "official_final_url": receipt.canonical_url,
        "source": "kaspi_ofd_qr_url",
        "suspicious_signals": [],
        "notes": ["Payment accepted only from deterministic receipt.kaspi.kz verification; AI was not used."],
    }


async def _verify_fiscal_receipt(
    receipt_url: str,
    *,
    expected_amount: int,
    offered_at: Any,
) -> KaspiFiscalReceipt:
    expected_bin = settings.payment_seller_bin
    expected_recipient = str(settings.kaspi_payment_recipient or "").strip()
    if not expected_bin and not expected_recipient:
        raise HTTPException(
            status_code=503,
            detail="Получатель KORGAN не настроен. Оплата не разблокирована; повторно платить не нужно.",
        )
    try:
        receipt = await fetch_kaspi_ofd_receipt(receipt_url)
    except KaspiOFDVerificationError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Фискальный чек не подтверждён Kaspi ОФД: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Kaspi ОФД временно недоступен. Повторно платить не нужно — проверьте ту же QR-ссылку позже.",
        ) from exc

    issues = fiscal_receipt_issues(
        receipt,
        expected_amount,
        expected_recipient=expected_recipient,
        expected_bin=expected_bin,
        offered_at=offered_at,
    )
    allowed_rnms = _configured_values(settings.payment_rnm)
    if allowed_rnms and receipt.rnm not in allowed_rnms:
        issues.append("РНМ фискального чека не принадлежит кассе KORGAN")
    if issues:
        raise HTTPException(
            status_code=422,
            detail="Фискальный чек не прошёл проверку Kaspi ОФД: " + "; ".join(issues[:7]),
        )
    return receipt


async def _consultation_created_at(order_id: int, user_id: int) -> Any:
    return await consultation_store._require_pool().fetchval(
        "SELECT created_at FROM consultation_payment_orders WHERE id=$1 AND user_id=$2",
        order_id,
        user_id,
    )


# Disable the old image/PDF payment-verification routes. Cached clients fail
# closed instead of falling back to ReceiptAnalyzer/OpenAI.
v4._drop_route("/miniapp/consultation/payments/{order_id}/receipt", "POST")
v5._drop("/miniapp/documents/payments/{order_id}/receipt", "POST")


@app.post("/miniapp/consultation/payments/{order_id}/receipt")
async def consultation_receipt_file_disabled(order_id: int) -> dict[str, Any]:
    raise HTTPException(
        status_code=415,
        detail="Фото/PDF больше не подтверждают оплату. Отсканируйте QR фискального чека и используйте ссылку receipt.kaspi.kz.",
    )


@app.post("/miniapp/documents/payments/{order_id}/receipt")
async def document_receipt_file_disabled(order_id: int) -> dict[str, Any]:
    raise HTTPException(
        status_code=415,
        detail="Фото/PDF больше не подтверждают оплату. Отсканируйте QR фискального чека и используйте ссылку receipt.kaspi.kz.",
    )


_original_answer_paid_order = v4._answer_paid_order


async def _locked_answer_paid_order(*, identity: str, state: dict[str, Any], order: consultation_store.ConsultationOrder) -> dict[str, Any]:
    async def operation() -> dict[str, Any]:
        fresh = await consultation_store.get_consultation_order(order.id, order.user_id)
        if fresh is None:
            raise HTTPException(status_code=404, detail="Платёжный запрос не найден")
        if fresh.status == "consumed":
            raise HTTPException(status_code=409, detail="Эта оплаченная консультация уже была выдана")
        if fresh.status != "paid":
            raise HTTPException(status_code=409, detail="Оплата консультации ещё не подтверждена")
        return await _original_answer_paid_order(identity=identity, state=state, order=fresh)

    return await _locked(
        consultation_store._require_pool(),
        _lock_key("miniapp-consultation-delivery", order.id),
        operation,
    )


# Also protects the existing /retry route from double taps.
v4._answer_paid_order = _locked_answer_paid_order


_original_run_approved_document = v5._run_approved_document


async def _locked_run_approved_document(
    order: document_store.DocumentPaymentOrder,
    *,
    x_telegram_init_data: str,
) -> dict[str, Any]:
    async def operation() -> dict[str, Any]:
        fresh = await document_store.get_document_order(order.id, user_key=order.user_key)
        if fresh is None:
            raise HTTPException(status_code=404, detail="Платёжный запрос не найден")
        if fresh.status == "consumed":
            raise HTTPException(status_code=409, detail="Эта оплата уже использована для документа")
        if fresh.status != "approved":
            raise HTTPException(status_code=409, detail="Оплата документа ещё не подтверждена")
        return await _original_run_approved_document(fresh, x_telegram_init_data=x_telegram_init_data)

    return await _locked(
        document_store._require_pool(),
        _lock_key("miniapp-document-generation", order.id),
        operation,
    )


# v5.generate_document resolves this global at request time; replacing it keeps
# the existing generation endpoint while adding server-side idempotency.
v5._run_approved_document = _locked_run_approved_document


async def _never_auto_approve_legacy_ai(
    order: document_store.DocumentPaymentOrder,
    *,
    user_key: str,
) -> document_store.DocumentPaymentOrder:
    # Legacy awaiting_admin records may contain AI-parsed receipts. They remain
    # locked until the client submits the official fiscal QR URL.
    return order


v5._auto_approve_stored = _never_auto_approve_legacy_ai


@app.post("/miniapp/consultation/payments/{order_id}/receipt-url")
async def consultation_receipt_url(
    order_id: int,
    payload: FiscalReceiptUrl,
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    identity = core.legacy._identity(x_telegram_init_data)
    state = await core.legacy._require_consent(identity)
    user_id = v4._quota_user_id(identity)
    order = await consultation_store.get_consultation_order(order_id, user_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Платёжный запрос не найден")
    if order.status == "consumed":
        raise HTTPException(status_code=409, detail="Эта оплаченная консультация уже была выдана")
    if order.status == "paid":
        return await v4._answer_paid_order(identity=identity, state=state, order=order)
    if order.status != "pending":
        raise HTTPException(status_code=409, detail="Этот платёжный запрос уже закрыт")

    offered_at = await _consultation_created_at(order.id, user_id)
    receipt = await _verify_fiscal_receipt(
        payload.receipt_url,
        expected_amount=order.amount_kzt,
        offered_at=offered_at,
    )
    accepted = await consultation_store.accept_consultation_receipt(
        order_id=order.id,
        user_id=user_id,
        receipt_hash=receipt.receipt_fingerprint,
        transaction_id=receipt.transaction_id,
    )
    if not accepted:
        latest = await consultation_store.get_consultation_order(order.id, user_id)
        if latest is not None and latest.status == "paid":
            return await v4._answer_paid_order(identity=identity, state=state, order=latest)
        if latest is not None and latest.status == "consumed":
            raise HTTPException(status_code=409, detail="Эта оплаченная консультация уже была выдана")
        raise HTTPException(
            status_code=409,
            detail="Этот фискальный чек уже использован или платёжный запрос уже обработан",
        )

    paid = await consultation_store.get_consultation_order(order.id, user_id)
    if paid is None or paid.status != "paid":
        raise HTTPException(status_code=409, detail="Не удалось восстановить подтверждённую оплату")
    return await v4._answer_paid_order(identity=identity, state=state, order=paid)


@app.post("/miniapp/documents/payments/{order_id}/receipt-url")
async def document_receipt_url(
    order_id: int,
    payload: FiscalReceiptUrl,
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    identity = core.legacy._identity(x_telegram_init_data)
    await core.legacy._require_consent(identity)
    user_key = core.store.user_key(identity)
    order = await document_store.get_document_order(order_id, user_key=user_key)
    if order is None:
        raise HTTPException(status_code=404, detail="Платёжный запрос не найден")
    if order.status == "consumed":
        raise HTTPException(status_code=409, detail="Эта оплата уже использована для документа")
    if order.status == "approved":
        return await v5._run_approved_document(order, x_telegram_init_data=x_telegram_init_data)
    if order.status not in {"pending_receipt", "awaiting_admin"}:
        raise HTTPException(status_code=409, detail="Этот платёжный запрос уже закрыт")

    offered_at = await v5._order_created_at(order.id, user_key)
    receipt = await _verify_fiscal_receipt(
        payload.receipt_url,
        expected_amount=order.amount_kzt,
        offered_at=offered_at,
    )

    if order.status == "pending_receipt":
        accepted = await document_store.accept_document_receipt_precheck(
            order_id=order.id,
            user_key=user_key,
            receipt_hash=receipt.receipt_fingerprint,
            transaction_id=receipt.transaction_id,
            receipt_check=_fiscal_payload(receipt),
        )
        if not accepted:
            latest = await document_store.get_document_order(order.id, user_key=user_key)
            if latest is not None and latest.status == "approved":
                return await v5._run_approved_document(latest, x_telegram_init_data=x_telegram_init_data)
            raise HTTPException(
                status_code=409,
                detail="Этот фискальный чек уже использован или платёжный запрос уже обработан",
            )
    else:
        belongs = await v5._registered_receipt_belongs_to_order(order.id, receipt.receipt_fingerprint)
        if not belongs:
            raise HTTPException(
                status_code=409,
                detail="Для этой заявки используйте тот же фискальный QR-чек, который был привязан ранее",
            )

    latest = await document_store.get_document_order(order.id, user_key=user_key)
    if latest is None:
        raise HTTPException(status_code=409, detail="Не удалось восстановить платёжный запрос")
    if latest.status == "awaiting_admin":
        approved = await document_store.decide_document_order(
            latest.id,
            approved=True,
            note="Kaspi OFD deterministic fiscal QR verification passed",
        )
        if not approved:
            latest = await document_store.get_document_order(latest.id, user_key=user_key)
            if latest is None or latest.status != "approved":
                raise HTTPException(status_code=409, detail="Статус оплаты изменился; обновите экран")
        else:
            latest = await document_store.get_document_order(latest.id, user_key=user_key)
    if latest is None or latest.status != "approved":
        raise HTTPException(status_code=409, detail="Оплата не подтверждена")

    return await v5._run_approved_document(latest, x_telegram_init_data=x_telegram_init_data)


# Keep the current 1.0.0 contract required by the live frontend, but expose the
# verifier mode explicitly for hardening tests and future UI checks.
v5._drop("/miniapp/parity", "GET")


@app.get("/miniapp/parity")
async def parity() -> dict[str, Any]:
    payload = await v5.parity()
    payload.update({
        "api_version": "1.0.0",
        "parity_revision": PARITY_REVISION,
        "automatic_receipt_verification": True,
        "receipt_verification_mode": "kaspi_ofd_fiscal_qr_url",
        "receipt_ai_decision": False,
        "document_manual_confirmation": False,
        "document_payment_admin_configured": False,
    })
    return payload
