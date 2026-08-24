from __future__ import annotations

import hashlib
import time
from typing import Any

from fastapi import File, Header, HTTPException, UploadFile

from korgan import miniapp_api_v3 as runtime
from korgan.consultation_quota import (
    ConsultationOrder,
    accept_consultation_receipt,
    close_consultation_store,
    create_consultation_order,
    get_consultation_order,
    init_consultation_store,
    mark_consultation_consumed,
    receipt_fingerprint,
    release_free_consultation,
    reserve_free_consultation,
    strict_consultation_receipt_issues,
)
from korgan.payment import ReceiptAnalyzer

core = runtime.core
app = runtime.app
settings = runtime.settings
service = runtime.service
PARITY_REVISION = "2026-08-24.3"
_RECEIPT_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}


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


# Replace v2's direct unlimited consultation and v3's parity probe before the
# ASGI app starts. All other v2/v3 endpoints remain unchanged.
_drop_route("/miniapp/consultation", "POST")
_drop_route("/miniapp/parity", "GET")


@app.on_event("startup")
async def _quota_startup() -> None:
    await init_consultation_store(settings)


@app.on_event("shutdown")
async def _quota_shutdown() -> None:
    await close_consultation_store()


def _quota_user_id(identity: str) -> int:
    try:
        return int(identity)
    except (TypeError, ValueError):
        # Stable negative id for explicitly enabled staging/dev auth. Real
        # Telegram WebApp identities are numeric and therefore share quota with
        # the production Telegram agent exactly.
        value = int(hashlib.sha256(str(identity).encode()).hexdigest()[:15], 16)
        return -(value or 1)


def _payment_payload(order: ConsultationOrder) -> dict[str, Any]:
    return {
        "order_id": order.id,
        "amount_kzt": order.amount_kzt,
        "kaspi_url": settings.kaspi_payment_url,
        "status": order.status,
        "receipt_accept": ["PDF", "JPG", "JPEG", "PNG", "WEBP"],
    }


def _append_case_conversation(
    case: dict[str, Any] | None,
    *,
    question: str,
    answer: str,
    urls: list[str],
) -> None:
    if case is None:
        return
    conversation = list(case.get("conversation") or [])
    conversation.extend([
        {"role": "user", "text": question, "ts": int(time.time())},
        {"role": "ai", "text": answer, "sources": list(urls or []), "ts": int(time.time())},
    ])
    case["conversation"] = conversation[-core._MAX_CONVERSATION_MESSAGES :]


async def _answer_paid_order(
    *,
    identity: str,
    state: dict[str, Any],
    order: ConsultationOrder,
) -> dict[str, Any]:
    if order.status != "paid":
        raise HTTPException(status_code=409, detail="Этот платёжный запрос ещё не подтверждён или уже использован")

    try:
        answer, urls = await service.consult(
            order.question,
            case_context=order.case_context,
            language="kk" if order.language == "kk" else "ru",
        )
    except Exception as exc:
        # The order intentionally remains paid so the client can retry without
        # paying again, matching the Telegram agent's paid-consultation flow.
        raise HTTPException(
            status_code=503,
            detail="Чек уже принят, но юридический AI временно не ответил. Повторная оплата не нужна.",
        ) from exc

    pending = dict(state.get("pending_consultations") or {})
    case_id = str(pending.get(str(order.id)) or "")
    case = state.get("cases", {}).get(case_id) if case_id else None
    _append_case_conversation(case, question=order.question, answer=answer, urls=list(urls or []))
    pending.pop(str(order.id), None)
    state["pending_consultations"] = pending
    await core.store.save(identity, state)

    if not await mark_consultation_consumed(order.id, order.user_id):
        raise HTTPException(status_code=409, detail="Оплаченная консультация уже была использована")

    return {
        "answer": answer,
        "sources": list(urls or []),
        "payment_required": False,
        "paid": True,
        "order_id": order.id,
    }


@app.get("/miniapp/parity")
async def parity() -> dict[str, Any]:
    inner = getattr(service, "inner", None)
    stable = getattr(inner, "stable", None)
    return {
        "status": "ok",
        "api_version": "0.9.0",
        "parity_revision": PARITY_REVISION,
        "legal_runtime": "strict_bot",
        "service_outer": type(service).__name__,
        "service_claim_mux": type(inner).__name__ if inner is not None else "",
        "service_stable": type(stable).__name__ if stable is not None else "",
        "claim_pipeline_v2_mode": runtime.claim_pipeline_v2_mode(),
        "word_quality_target": "10/10",
        "preliminary_fallback": True,
        "official_corpus_refresh": bool(runtime._corpus_task is not None),
        "consultation_limit_enabled": bool(settings.consultation_limit_enabled),
        "free_consultations_per_day": int(settings.free_consultations_per_day),
        "consultation_price_kzt": int(settings.consultation_price_kzt),
        "document_payments_enabled": bool(settings.payments_enabled),
        "document_price_kzt": int(settings.document_price_kzt),
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
        "document_price_kzt": int(settings.document_price_kzt),
        "document_payments_enabled": bool(settings.payments_enabled),
        "kaspi_url": settings.kaspi_payment_url if settings.consultation_limit_enabled or settings.payments_enabled else "",
    }


@app.post("/miniapp/consultation")
async def consultation(
    payload: core.legacy.ConsultationRequest,
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    identity = core.legacy._identity(x_telegram_init_data)
    state = await core.legacy._require_consent(identity)
    case: dict[str, Any] | None = None
    case_context = ""
    if payload.case_id:
        case = state["cases"].get(payload.case_id)
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        case_context = core._case_context(case)

    language = "kk" if payload.language == "kk" else "ru"
    quota_id = _quota_user_id(identity)
    used: int | None = 0
    if settings.consultation_limit_enabled:
        used = await reserve_free_consultation(quota_id, settings.free_consultations_per_day)
        if used is None:
            order = await create_consultation_order(
                user_id=quota_id,
                chat_id=quota_id,
                question=payload.message,
                case_context=case_context,
                language=language,
                amount_kzt=settings.consultation_price_kzt,
            )
            pending = dict(state.get("pending_consultations") or {})
            pending[str(order.id)] = payload.case_id or ""
            state["pending_consultations"] = pending
            await core.store.save(identity, state)
            return {
                "answer": "",
                "sources": [],
                "payment_required": True,
                "free_remaining": 0,
                "payment": _payment_payload(order),
            }

    try:
        answer, urls = await service.consult(
            payload.message,
            case_context=case_context,
            language=language,
        )
    except Exception as exc:
        if settings.consultation_limit_enabled and used:
            await release_free_consultation(quota_id)
        raise HTTPException(
            status_code=502,
            detail="Не удалось выполнить юридический поиск. Бесплатный запрос не списан — попробуйте ещё раз.",
        ) from exc

    _append_case_conversation(case, question=payload.message, answer=answer, urls=list(urls or []))
    if case is not None:
        await core.store.save(identity, state)

    remaining = (
        max(settings.free_consultations_per_day - int(used or 0), 0)
        if settings.consultation_limit_enabled
        else None
    )
    return {
        "answer": answer,
        "sources": list(urls or []),
        "payment_required": False,
        "free_remaining": remaining,
    }


@app.post("/miniapp/consultation/payments/{order_id}/receipt")
async def consultation_receipt(
    order_id: int,
    file: UploadFile = File(...),
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    identity = core.legacy._identity(x_telegram_init_data)
    state = await core.legacy._require_consent(identity)
    quota_id = _quota_user_id(identity)
    order = await get_consultation_order(order_id, quota_id)
    if order is None or order.status != "pending":
        raise HTTPException(status_code=409, detail="Этот платёжный запрос уже обработан или устарел")

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
        raise HTTPException(status_code=502, detail="Не удалось проверить чек. Консультация не разблокирована.") from exc

    issues = strict_consultation_receipt_issues(check, order.amount_kzt)
    if issues:
        raise HTTPException(
            status_code=422,
            detail="Чек не прошёл автоматическую проверку: " + "; ".join(issues[:6]),
        )

    accepted = await accept_consultation_receipt(
        order_id=order.id,
        user_id=quota_id,
        receipt_hash=receipt_fingerprint(data),
        transaction_id=check.receipt_or_transaction_id,
    )
    if not accepted:
        raise HTTPException(
            status_code=409,
            detail="Этот чек или номер операции уже использовался либо платёжный запрос уже обработан",
        )

    paid_order = await get_consultation_order(order.id, quota_id)
    if paid_order is None:
        raise HTTPException(status_code=409, detail="Не удалось восстановить оплаченный запрос")
    return await _answer_paid_order(identity=identity, state=state, order=paid_order)


@app.post("/miniapp/consultation/payments/{order_id}/retry")
async def retry_paid_consultation(
    order_id: int,
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    identity = core.legacy._identity(x_telegram_init_data)
    state = await core.legacy._require_consent(identity)
    quota_id = _quota_user_id(identity)
    order = await get_consultation_order(order_id, quota_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Платёжный запрос не найден")
    return await _answer_paid_order(identity=identity, state=state, order=order)
