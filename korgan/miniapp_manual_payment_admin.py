from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any

import httpx
from fastapi import File, Header, HTTPException, UploadFile

from korgan import miniapp_api_ofd as ofd
from korgan import miniapp_api_ofd_upload as upload_runtime
from korgan import miniapp_document_payments as document_store
from korgan.kaspi_ofd import KaspiFiscalReceipt

LOGGER = logging.getLogger(__name__)

app = upload_runtime.app
core = ofd.core
settings = ofd.settings
v4 = ofd.v4
v5 = ofd.v5

_TELEGRAM_API = "https://api.telegram.org"
_SEND_TIMEOUT = 30.0


def _payment_payload(order: document_store.DocumentPaymentOrder) -> dict[str, Any]:
    return {
        "order_id": order.id,
        "case_id": order.case_id,
        "document_type": order.document_type,
        "amount_kzt": order.amount_kzt,
        "kaspi_url": settings.kaspi_payment_url,
        "status": order.status,
        "approval_required": True,
        "decision_note": order.decision_note,
        "receipt_accept": ["PDF", "JPG", "JPEG", "PNG", "WEBP"],
    }


def _manual_receipt_payload(receipt: KaspiFiscalReceipt, *, warning: str = "") -> dict[str, Any]:
    payload = ofd._fiscal_payload(receipt)
    payload["manual_confirmation_required"] = True
    payload["automatic_final_approval"] = False
    if warning:
        notes = list(payload.get("notes") or [])
        notes.append(f"Автоматическая сверка не финальная: {warning}")
        payload["notes"] = notes
        payload["precheck_warning"] = warning[:1000]
    return payload


def _caption(order: document_store.DocumentPaymentOrder, receipt: KaspiFiscalReceipt, *, warning: str = "") -> str:
    warning_line = f"\n⚠️ Предварительная проверка: {warning[:500]}" if warning else "\n✅ Фискальные поля считаны"
    return (
        "🧾 KORGAN · РУЧНАЯ ПРОВЕРКА ОПЛАТЫ\n\n"
        f"Заказ: #{order.id}\n"
        f"Дело: {order.case_id}\n"
        f"Документ: {order.document_type}\n"
        f"Сумма: {order.amount_kzt:,} ₸\n"
        f"Продавец: {receipt.seller_name or '—'}\n"
        f"БИН: {receipt.seller_bin or '—'}\n"
        f"РНМ: {receipt.rnm or '—'}\n"
        f"ФП: {receipt.fp or '—'}\n"
        f"№ чека: {receipt.receipt_number or '—'}\n"
        f"Дата/время: {receipt.sale_datetime or '—'}\n"
        f"ОФД: {receipt.ofd_name or '—'}\n"
        f"Оплата: {receipt.payment_method or '—'}"
        f"{warning_line}\n\n"
        "Сверьте этот платёж в истории Kaspi Pay. Затем откройте MiniApp → Профиль → «Проверка оплат» и нажмите «Подтвердить» или «Отклонить»."
    )[:1024]


async def _send_receipt_to_admin(
    admin_id: int,
    *,
    order: document_store.DocumentPaymentOrder,
    receipt: KaspiFiscalReceipt,
    filename: str,
    data: bytes,
    content_type: str,
    warning: str = "",
) -> bool:
    token = str(settings.telegram_bot_token or "").strip()
    if not token:
        LOGGER.error("KORGAN manual payment: TELEGRAM_BOT_TOKEN missing")
        return False

    form: dict[str, str] = {
        "chat_id": str(admin_id),
        "caption": _caption(order, receipt, warning=warning),
    }
    miniapp_url = os.getenv("MINIAPP_PUBLIC_URL", "").strip()
    if miniapp_url.startswith("https://"):
        form["reply_markup"] = json.dumps(
            {
                "inline_keyboard": [[
                    {
                        "text": "Открыть проверку оплат",
                        "web_app": {"url": miniapp_url},
                    }
                ]]
            },
            ensure_ascii=False,
        )

    try:
        async with httpx.AsyncClient(timeout=_SEND_TIMEOUT) as client:
            response = await client.post(
                f"{_TELEGRAM_API}/bot{token}/sendDocument",
                data=form,
                files={"document": (filename, data, content_type or "application/octet-stream")},
            )
    except httpx.HTTPError as exc:
        LOGGER.warning("KORGAN manual payment admin notify network failure admin_id=%s detail=%s", admin_id, exc)
        return False

    body: dict[str, Any] = {}
    try:
        body = response.json()
    except ValueError:
        pass
    if not body.get("ok"):
        LOGGER.warning(
            "KORGAN manual payment admin notify failed admin_id=%s status=%s detail=%s",
            admin_id,
            response.status_code,
            body.get("description") or "unknown",
        )
        return False
    LOGGER.info("KORGAN manual payment receipt sent admin_id=%s order_id=%s", admin_id, order.id)
    return True


async def _notify_admins(
    *,
    order: document_store.DocumentPaymentOrder,
    receipt: KaspiFiscalReceipt,
    filename: str,
    data: bytes,
    content_type: str,
    warning: str = "",
) -> None:
    admin_ids = sorted(settings.admin_ids)
    if not admin_ids:
        LOGGER.error("KORGAN manual payment: ADMIN_TELEGRAM_IDS is empty order_id=%s", order.id)
        return
    for admin_id in admin_ids:
        await _send_receipt_to_admin(
            admin_id,
            order=order,
            receipt=receipt,
            filename=filename,
            data=data,
            content_type=content_type,
            warning=warning,
        )


# Replace automatic document receipt acceptance with a manual-admin queue.
# Consultation payment remains unchanged.
v5._drop("/miniapp/documents/payments/{order_id}/receipt", "POST")
v5._drop("/miniapp/parity", "GET")
v5._drop("/miniapp/pricing", "GET")


@app.get("/miniapp/parity")
async def parity() -> dict[str, Any]:
    payload = await ofd.parity()
    payload.update(
        {
            "document_manual_confirmation": True,
            "document_payment_admin_configured": bool(settings.admin_ids),
            "automatic_receipt_verification": False,
            "receipt_verification_mode": "kaspi_receipt_precheck_then_admin",
            "receipt_ai_decision": False,
        }
    )
    return payload


@app.get("/miniapp/pricing")
async def pricing(x_telegram_init_data: str = Header(default="")) -> dict[str, Any]:
    payload = await v5.pricing(x_telegram_init_data)
    payload["document_manual_confirmation"] = True
    payload["automatic_receipt_verification"] = False
    payload["document_payment_admin_configured"] = bool(settings.admin_ids)
    return payload


@app.post("/miniapp/documents/payments/{order_id}/receipt")
async def document_receipt_upload_manual(
    order_id: int,
    file: UploadFile = File(...),
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
        return {
            "ok": True,
            "payment_required": False,
            "generation_started": False,
            "payment": _payment_payload(order),
            "message": "Оплата уже подтверждена администратором. Повторно платить не нужно.",
        }
    if order.status not in {"pending_receipt", "awaiting_admin"}:
        raise HTTPException(status_code=409, detail="Этот платёжный запрос уже закрыт")

    filename = (file.filename or "receipt").strip()
    content_type = file.content_type or "application/octet-stream"
    data = await file.read(core._MAX_UPLOAD_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail="Пустой файл")
    if len(data) > core._MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Файл больше 20 МБ")
    await file.seek(0)

    receipt_url, uploaded_receipt = await upload_runtime._receipt_from_upload(file)
    token = upload_runtime._uploaded_receipt_ctx.set(uploaded_receipt)
    try:
        offered_at = await v5._order_created_at(order.id, user_key)
        warning = ""
        receipt: KaspiFiscalReceipt | None = None
        try:
            receipt = await ofd._verify_fiscal_receipt(
                receipt_url,
                expected_amount=order.amount_kzt,
                offered_at=offered_at,
            )
        except HTTPException as exc:
            # Manual confirmation is the final authority. A fully parsed electronic
            # Kaspi PDF with QR/PDF cross-check may still enter the admin queue even
            # if the remote OFD endpoint returns an incomplete client-rendered page.
            if uploaded_receipt is None:
                raise
            receipt = uploaded_receipt
            warning = str(exc.detail or "Kaspi ОФД не дал полный серверный ответ")

        if receipt is None:
            raise HTTPException(status_code=422, detail="Не удалось прочитать данные Kaspi-чека")
        if int(receipt.amount_kzt or 0) != int(order.amount_kzt):
            raise HTTPException(
                status_code=422,
                detail=f"Сумма чека {int(receipt.amount_kzt or 0)} ₸ не соответствует заказу {order.amount_kzt} ₸",
            )

        receipt_hash = hashlib.sha256(data).hexdigest()
        newly_registered = False
        if order.status == "pending_receipt":
            accepted = await document_store.accept_document_receipt_precheck(
                order_id=order.id,
                user_key=user_key,
                receipt_hash=receipt_hash,
                transaction_id=str(receipt.receipt_number or receipt.transaction_id or ""),
                receipt_check=_manual_receipt_payload(receipt, warning=warning),
            )
            if not accepted:
                latest = await document_store.get_document_order(order.id, user_key=user_key)
                if latest is None or latest.status != "awaiting_admin":
                    raise HTTPException(
                        status_code=409,
                        detail="Этот чек/номер операции уже использован или запрос уже обработан",
                    )
                order = latest
            else:
                newly_registered = True
                latest = await document_store.get_document_order(order.id, user_key=user_key)
                if latest is not None:
                    order = latest
        else:
            belongs = await v5._registered_receipt_belongs_to_order(order.id, receipt_hash)
            if not belongs:
                raise HTTPException(
                    status_code=409,
                    detail="Для этой заявки уже отправлен другой чек на ручную проверку",
                )

        if order.status != "awaiting_admin":
            raise HTTPException(status_code=409, detail="Статус оплаты изменился; обновите экран")

        if newly_registered:
            await _notify_admins(
                order=order,
                receipt=receipt,
                filename=filename,
                data=data,
                content_type=content_type,
                warning=warning,
            )

        return {
            "ok": True,
            "payment_required": True,
            "generation_started": False,
            "payment": _payment_payload(order),
            "message": "Чек отправлен администраторам. Повторно платить не нужно — ожидайте ручного подтверждения.",
        }
    finally:
        upload_runtime._uploaded_receipt_ctx.reset(token)
