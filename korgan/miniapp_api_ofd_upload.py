from __future__ import annotations

import hashlib
import io
import re
from contextvars import ContextVar
from dataclasses import replace
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qsl, urlparse

from fastapi import File, Header, HTTPException, UploadFile
from pypdf import PdfReader

from korgan import miniapp_api_ofd as ofd
from korgan.fiscal_qr_extract import extract_kaspi_fiscal_qr_url
from korgan.kaspi_ofd import (
    KaspiFiscalReceipt,
    KaspiOFDVerificationError,
    _parse_datetime,
    canonicalize_kaspi_receipt_url,
)
from korgan.kaspi_payment_resilience import install_ofd_retry
from korgan.kaspi_receipt_policy import install_receipt_policy

app = ofd.app
core = ofd.core
_ALLOWED = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}
_MAX_PDF_PAGES = 3
_QR_TIME_TOLERANCE = timedelta(minutes=2)

# Retry only transient Kaspi OFD/network failures. Invalid/mismatched receipts
# remain fail-closed and are never accepted just because a retry happened.
install_ofd_retry(ofd)

# Enforce the production MiniApp receipt policy: fresh timestamp for this order,
# seller/merchant identity, BIN/RNM, ZNM, FP, Kaspi OFD and amount. Address and
# payer name are deliberately not payment blockers.
install_receipt_policy(ofd)

# Some receipt.kaspi.kz /web/fiscal responses are rendered client-side. A plain
# backend HTTP fetch can therefore contain only the application shell while the
# uploaded electronic Kaspi PDF already contains the fiscal fields. Keep the
# official QR mandatory and bind the PDF fields to the QR values (RNM, FP,
# amount, timestamp) before using the PDF as a deterministic field source.
_uploaded_receipt_ctx: ContextVar[KaspiFiscalReceipt | None] = ContextVar(
    "korgan_uploaded_kaspi_receipt",
    default=None,
)


def _clean_lines(text: str) -> list[str]:
    result: list[str] = []
    for raw in str(text or "").splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if line:
            result.append(line)
    return result


def _match(text: str, pattern: str) -> str:
    found = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
    return found.group(1).strip() if found else ""


def _amount_int(value: str) -> int:
    digits = re.sub(r"\D", "", str(value or ""))
    return int(digits or 0)


def _parse_uploaded_pdf_text(
    text: str,
    receipt_url: str,
    *,
    body_sha256: str,
) -> KaspiFiscalReceipt | None:
    raw_text = str(text or "").replace("\xa0", " ")
    lines = _clean_lines(raw_text)
    folded = raw_text.casefold()
    if "фискальный чек" not in folded:
        return None

    receipt_number = _match(
        raw_text,
        r"№\s*чека(?:\s*\(RRN\))?\s*[:№\-—]?\s*([A-Za-z0-9_-]{4,120})",
    )
    sale_datetime = _match(
        raw_text,
        r"(\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}(?::\d{2})?)",
    )
    seller_bin = _match(
        raw_text,
        r"ИИН/БИН\s+продавца\s*[:№\-—]?\s*(\d{12})",
    )
    rnm = _match(
        raw_text,
        r"(?:^|\n)\s*РНМ\s*[:№\-—]?\s*([A-Za-zА-Яа-я0-9_-]{4,40})",
    )
    znm = _match(
        raw_text,
        r"(?:^|\n)\s*ЗНМ\s*[:№\-—]?\s*([A-Za-zА-Яа-я0-9_-]{4,40})",
    )
    fp = _match(
        raw_text,
        r"(?:^|\n)\s*ФП\s*[:№\-—]?\s*([A-Za-zА-Яа-я0-9_-]{4,40})",
    )
    ofd_name = _match(
        raw_text,
        r"(?:^|\n)\s*ОФД\s*[:№\-—]?\s*([^\n]{2,80})",
    )
    payment_method = _match(
        raw_text,
        r"(?:^|\n)\s*Оплачено\s*[:№\-—]?\s*([^\n]{2,120})",
    )

    seller_name = ""
    for line in lines:
        if re.match(r"^(?:ИП|ТОО)\b", line, flags=re.IGNORECASE):
            seller_name = line
            break
    if not seller_name:
        try:
            sale_index = next(i for i, line in enumerate(lines) if line.casefold() == "продажа")
        except StopIteration:
            sale_index = -1
        if sale_index > 0:
            for candidate in reversed(lines[:sale_index]):
                folded_candidate = candidate.casefold()
                if (
                    candidate
                    and "фискальный чек" not in folded_candidate
                    and "оплата совершена" not in folded_candidate
                    and "платеж успешно" not in folded_candidate
                    and "₸" not in candidate
                ):
                    seller_name = candidate
                    break

    amount_raw = _match(
        raw_text,
        r"(?:Оплата совершена|Плат[её]ж успешно совершен)[^\d]{0,60}(\d+(?:[ .]\d{3})*)\s*₸",
    )
    if not amount_raw:
        amount_raw = _match(raw_text, r"(?m)^\s*(\d+(?:[ .]\d{3})*)\s*₸\s*$")
    amount_kzt = _amount_int(amount_raw)

    successful_marker = (
        "оплата совершена" in folded
        or "платеж успешно совершен" in folded
        or "платёж успешно совершен" in folded
    )
    successful = bool(
        successful_marker
        and receipt_number
        and amount_kzt
        and sale_datetime
        and seller_name
        and seller_bin
        and rnm
        and znm
        and fp
        and "kaspi" in ofd_name.casefold()
        and "офд" in ofd_name.casefold()
        and "kaspi" in payment_method.casefold()
    )

    canonical = canonicalize_kaspi_receipt_url(receipt_url)
    parsed = urlparse(canonical)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    return KaspiFiscalReceipt(
        canonical_url=canonical,
        body_sha256=body_sha256,
        ext_transaction_id=query.get("extTranId", "").strip(),
        receipt_number=receipt_number[:120],
        successful=successful,
        amount_kzt=amount_kzt,
        sale_datetime=sale_datetime[:120],
        seller_name=seller_name[:200],
        seller_bin=seller_bin[:12],
        rnm=rnm[:120],
        fp=fp[:160],
        ofd_name=ofd_name[:120],
        payment_method=payment_method[:120],
        raw_text=raw_text[:20_000],
    )


def _pdf_receipt(data: bytes, receipt_url: str) -> KaspiFiscalReceipt | None:
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        text = "\n".join((page.extract_text() or "") for page in reader.pages[:_MAX_PDF_PAGES])
    except Exception:
        return None
    if not text.strip():
        return None
    return _parse_uploaded_pdf_text(
        text,
        receipt_url,
        body_sha256=hashlib.sha256(data).hexdigest(),
    )


def _assert_qr_matches_uploaded_receipt(receipt_url: str, receipt: KaspiFiscalReceipt) -> None:
    canonical = canonicalize_kaspi_receipt_url(receipt_url)
    parsed = urlparse(canonical)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))

    if parsed.path == "/web/fiscal":
        qr_rnm = re.sub(r"\s+", "", query.get("f", ""))
        qr_fp = re.sub(r"\s+", "", query.get("i", ""))
        qr_amount_raw = query.get("s", "").replace(",", ".")
        try:
            qr_amount = int(float(qr_amount_raw))
        except (TypeError, ValueError):
            qr_amount = 0
        if qr_rnm != receipt.rnm:
            raise KaspiOFDVerificationError("РНМ в PDF не совпадает с фискальным QR Kaspi")
        if qr_fp != receipt.fp:
            raise KaspiOFDVerificationError("ФП в PDF не совпадает с фискальным QR Kaspi")
        if qr_amount != receipt.amount_kzt:
            raise KaspiOFDVerificationError("Сумма в PDF не совпадает с фискальным QR Kaspi")
        qr_time = _parse_datetime(query.get("t", ""))
        pdf_time = _parse_datetime(receipt.sale_datetime)
        if qr_time is None or pdf_time is None or abs(qr_time - pdf_time) > _QR_TIME_TOLERANCE:
            raise KaspiOFDVerificationError("Дата/время в PDF не совпадают с фискальным QR Kaspi")
        return

    ext_tran_id = query.get("extTranId", "").strip()
    if ext_tran_id and receipt.receipt_number and ext_tran_id != receipt.receipt_number:
        raise KaspiOFDVerificationError("Номер чека в PDF не совпадает с фискальным QR Kaspi")
    qr_time = _parse_datetime(query.get("sale_date", ""))
    pdf_time = _parse_datetime(receipt.sale_datetime)
    if qr_time is not None and pdf_time is not None and abs(qr_time - pdf_time) > _QR_TIME_TOLERANCE:
        raise KaspiOFDVerificationError("Дата/время в PDF не совпадают с фискальным QR Kaspi")


def _merge_remote_with_uploaded(
    remote: KaspiFiscalReceipt,
    uploaded: KaspiFiscalReceipt,
) -> KaspiFiscalReceipt:
    if remote.canonical_url != uploaded.canonical_url:
        raise KaspiOFDVerificationError("Фискальный QR не соответствует загруженному чеку")

    for attr, label in (
        ("receipt_number", "номер чека"),
        ("seller_bin", "БИН продавца"),
        ("rnm", "РНМ"),
        ("fp", "ФП"),
    ):
        remote_value = str(getattr(remote, attr, "") or "").strip()
        uploaded_value = str(getattr(uploaded, attr, "") or "").strip()
        if remote_value and uploaded_value and remote_value != uploaded_value:
            raise KaspiOFDVerificationError(f"{label} в PDF не совпадает с Kaspi ОФД")

    if remote.amount_kzt and uploaded.amount_kzt and remote.amount_kzt != uploaded.amount_kzt:
        raise KaspiOFDVerificationError("Сумма в PDF не совпадает с Kaspi ОФД")

    remote_time = _parse_datetime(remote.sale_datetime)
    uploaded_time = _parse_datetime(uploaded.sale_datetime)
    if (
        remote_time is not None
        and uploaded_time is not None
        and abs(remote_time - uploaded_time) > _QR_TIME_TOLERANCE
    ):
        raise KaspiOFDVerificationError("Дата/время в PDF не совпадают с Kaspi ОФД")

    combined_hash = hashlib.sha256(
        f"{remote.body_sha256}:{uploaded.body_sha256}".encode("utf-8")
    ).hexdigest()
    return replace(
        remote,
        body_sha256=combined_hash,
        receipt_number=remote.receipt_number or uploaded.receipt_number,
        successful=bool(remote.successful or uploaded.successful),
        amount_kzt=remote.amount_kzt or uploaded.amount_kzt,
        sale_datetime=remote.sale_datetime or uploaded.sale_datetime,
        seller_name=remote.seller_name or uploaded.seller_name,
        seller_bin=remote.seller_bin or uploaded.seller_bin,
        rnm=remote.rnm or uploaded.rnm,
        fp=remote.fp or uploaded.fp,
        ofd_name=remote.ofd_name or uploaded.ofd_name,
        payment_method=remote.payment_method or uploaded.payment_method,
        raw_text=uploaded.raw_text if len(uploaded.raw_text) >= len(remote.raw_text) else remote.raw_text,
    )


_original_fetch_kaspi_ofd_receipt = ofd.fetch_kaspi_ofd_receipt


async def _fetch_kaspi_ofd_receipt_with_uploaded_pdf(
    url: str,
    *,
    timeout: float = 8.0,
) -> KaspiFiscalReceipt:
    remote = await _original_fetch_kaspi_ofd_receipt(url, timeout=timeout)
    uploaded = _uploaded_receipt_ctx.get()
    if uploaded is None:
        return remote
    _assert_qr_matches_uploaded_receipt(url, uploaded)
    return _merge_remote_with_uploaded(remote, uploaded)


_fetch_kaspi_ofd_receipt_with_uploaded_pdf._korgan_uploaded_pdf_bridge = True  # type: ignore[attr-defined]
ofd.fetch_kaspi_ofd_receipt = _fetch_kaspi_ofd_receipt_with_uploaded_pdf

# Replace the fail-closed compatibility stubs with deterministic local QR
# extraction. Existing React clients can upload the Kaspi receipt directly.
ofd.v4._drop_route("/miniapp/consultation/payments/{order_id}/receipt", "POST")
ofd.v5._drop("/miniapp/documents/payments/{order_id}/receipt", "POST")


async def _receipt_from_upload(file: UploadFile) -> tuple[str, KaspiFiscalReceipt | None]:
    filename = (file.filename or "receipt").strip()
    extension = core.legacy._extension(filename)
    if extension not in _ALLOWED:
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

    uploaded_receipt = _pdf_receipt(data, receipt_url) if extension == ".pdf" else None
    if extension == ".pdf" and uploaded_receipt is None:
        raise HTTPException(
            status_code=422,
            detail="Не удалось прочитать реквизиты электронного Kaspi-чека PDF.",
        )
    if uploaded_receipt is not None:
        try:
            _assert_qr_matches_uploaded_receipt(receipt_url, uploaded_receipt)
        except KaspiOFDVerificationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return receipt_url, uploaded_receipt


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
    receipt_url, uploaded_receipt = await _receipt_from_upload(file)
    token = _uploaded_receipt_ctx.set(uploaded_receipt)
    try:
        return await ofd.consultation_receipt_url(
            order_id,
            ofd.FiscalReceiptUrl(receipt_url=receipt_url),
            x_telegram_init_data,
        )
    finally:
        _uploaded_receipt_ctx.reset(token)


@app.post("/miniapp/documents/payments/{order_id}/receipt")
async def document_receipt_upload(
    order_id: int,
    file: UploadFile = File(...),
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    receipt_url, uploaded_receipt = await _receipt_from_upload(file)
    token = _uploaded_receipt_ctx.set(uploaded_receipt)
    try:
        return await ofd.document_receipt_url(
            order_id,
            ofd.FiscalReceiptUrl(receipt_url=receipt_url),
            x_telegram_init_data,
        )
    finally:
        _uploaded_receipt_ctx.reset(token)
