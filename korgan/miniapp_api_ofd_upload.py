from __future__ import annotations

from typing import Any

from fastapi import File, Header, HTTPException, UploadFile

from korgan import miniapp_api_ofd as ofd
from korgan.fiscal_qr_extract import extract_kaspi_fiscal_qr_url
from korgan.kaspi_payment_resilience import install_ofd_retry
from korgan.kaspi_receipt_policy import install_receipt_policy

app = ofd.app
core = ofd.core
_ALLOWED = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}

# Retry only transient Kaspi OFD/network failures. Invalid/mismatched receipts
# remain fail-closed and are never accepted just because a retry happened.
install_ofd_retry(ofd)

# Enforce the production MiniApp receipt policy: fresh timestamp for this order,
# seller/merchant identity, BIN/RNM, ZNM, FP, Kaspi OFD and amount. Address and
# payer name are deliberately not payment blockers.
install_receipt_policy(ofd)

# Replace the fail-closed compatibility stubs with deterministic local QR
# extraction. Existing React clients can upload the Kaspi receipt directly;
# approval is still based solely on receipt.kaspi.kz / Kaspi OFD.
ofd.v4._drop_route("/miniapp/consultation/payments/{order_id}/receipt", "POST")
ofd.v5._drop("/miniapp/documents/payments/{order_id}/receipt", "POST")


async def _receipt_url_from_upload(file: UploadFile) -> str:
    filename = (file.filename or "receipt").strip()
    if core.legacy._extension(filename) not in _ALLOWED:
        raise HTTPException(
            status_code=415,
            detail="Поддерживаются PDF/JPG/PNG/WEBP фискального чека Kaspi",
        )
    data = await file.read(core._MAX_UPLOAD_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail="Пустой файл")
    if len(data) > core._MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Файл больше 20 МБ")
    try:
        receipt_url = await extract_kaspi_fiscal_qr_url(data, filename, file.content_type or "")
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail="Не удалось прочитать фискальный QR на чеке Kaspi. Загрузите полный электронный чек или чёткое изображение с QR-кодом.",
        ) from exc
    if not receipt_url:
        raise HTTPException(
            status_code=422,
            detail="На чеке не найден фискальный QR Kaspi ОФД. Загрузите полный чек Kaspi, полученный после оплаты.",
        )
    return receipt_url


@app.get("/miniapp/consultation/payments/{order_id}")
async def consultation_payment_status(
    order_id: int,
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    identity = core.legacy._identity(x_telegram_init_data)
    await core.legacy._require_consent(identity)
    user_id = ofd.v4._quota_user_id(identity)
    order = await ofd.consultation_store.get_consultation_order(order_id, user_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Платёжный запрос не найден")
    return {
        "ok": True,
        "payment": {
            "order_id": order.id,
            "amount_kzt": order.amount_kzt,
            "status": order.status,
            "paid": order.status in {"paid", "consumed"},
        },
    }


@app.post("/miniapp/consultation/payments/{order_id}/receipt")
async def consultation_receipt_upload(
    order_id: int,
    file: UploadFile = File(...),
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    receipt_url = await _receipt_url_from_upload(file)
    return await ofd.consultation_receipt_url(
        order_id,
        ofd.FiscalReceiptUrl(receipt_url=receipt_url),
        x_telegram_init_data,
    )


@app.post("/miniapp/documents/payments/{order_id}/receipt")
async def document_receipt_upload(
    order_id: int,
    file: UploadFile = File(...),
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    receipt_url = await _receipt_url_from_upload(file)
    return await ofd.document_receipt_url(
        order_id,
        ofd.FiscalReceiptUrl(receipt_url=receipt_url),
        x_telegram_init_data,
    )
