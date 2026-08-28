from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from korgan import consultation_quota as consultation_store
from korgan import miniapp_api_ofd as ofd
from korgan import miniapp_api_ofd_upload as upload_runtime
from korgan import miniapp_document_payments as document_store
from korgan.payment_operation_lock import payment_operation_lock

app = upload_runtime.app
v4 = ofd.v4
v5 = ofd.v5

_ORIGINAL_ANSWER_PAID = ofd._original_answer_paid_order
_ORIGINAL_CREATE_DOCUMENT_ORDER = document_store.create_document_order
_ORIGINAL_RUN_APPROVED_DOCUMENT = ofd._original_run_approved_document


async def _shared_answer_paid_order(
    *,
    identity: str,
    state: dict[str, Any],
    order: consultation_store.ConsultationOrder,
) -> dict[str, Any]:
    async with payment_operation_lock(
        consultation_store._require_pool(),
        "consultation-delivery",
        order.id,
    ):
        fresh = await consultation_store.get_consultation_order(order.id, order.user_id)
        if fresh is None:
            raise HTTPException(status_code=404, detail="Платёжный запрос не найден")
        if fresh.status == "consumed":
            raise HTTPException(status_code=409, detail="Эта оплаченная консультация уже была выдана")
        if fresh.status != "paid":
            raise HTTPException(status_code=409, detail="Оплата консультации ещё не подтверждена")
        return await _ORIGINAL_ANSWER_PAID(identity=identity, state=state, order=fresh)


async def _locked_create_document_order(**kwargs: Any) -> document_store.DocumentPaymentOrder:
    user_key = str(kwargs.get("user_key") or "")
    case_id = str(kwargs.get("case_id") or "")
    if not user_key or not case_id:
        return await _ORIGINAL_CREATE_DOCUMENT_ORDER(**kwargs)
    async with payment_operation_lock(
        document_store._require_pool(),
        "miniapp-document-order",
        f"{user_key}:{case_id}",
    ):
        return await _ORIGINAL_CREATE_DOCUMENT_ORDER(**kwargs)


async def _shared_run_approved_document(
    order: document_store.DocumentPaymentOrder,
    *,
    x_telegram_init_data: str,
) -> dict[str, Any]:
    async with payment_operation_lock(
        document_store._require_pool(),
        "miniapp-document-generation",
        order.id,
    ):
        fresh = await document_store.get_document_order(order.id, user_key=order.user_key)
        if fresh is None:
            raise HTTPException(status_code=404, detail="Платёжный запрос не найден")
        if fresh.status == "consumed":
            raise HTTPException(status_code=409, detail="Эта оплата уже использована для документа")
        if fresh.status != "approved":
            raise HTTPException(status_code=409, detail="Оплата документа ещё не подтверждена")
        return await _ORIGINAL_RUN_APPROVED_DOCUMENT(
            fresh,
            x_telegram_init_data=x_telegram_init_data,
        )


# All assignments are process-local wrappers around the already-tested v4/v5
# implementation. No route or database schema is changed here.
v4._answer_paid_order = _shared_answer_paid_order
document_store.create_document_order = _locked_create_document_order
v5._run_approved_document = _shared_run_approved_document
