from __future__ import annotations

import hashlib
import time
from typing import Any

from fastapi import File, Header, HTTPException, UploadFile
from pydantic import BaseModel

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
from korgan.miniapp_document_payments import (
    DocumentPaymentOrder,
    accept_document_receipt_precheck,
    close_document_payment_store,
    consume_document_order,
    create_document_order,
    decide_document_order,
    get_document_order,
    get_scope_order,
    init_document_payment_store,
    list_document_orders_for_admin,
)
from korgan.payment import ReceiptAnalyzer, receipt_hard_issues

core = runtime.core
app = runtime.app
settings = runtime.settings
service = runtime.service
PARITY_REVISION = "2026-08-26.1"
_RECEIPT_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}


class AdminDocumentPaymentDecision(BaseModel):
    approved: bool
    note: str = ""


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


# Replace v2's direct unlimited consultation, direct document generation and
# v3's parity probe. All changes stay inside the dedicated Mini App ASGI app;
# strict_bot and Telegram polling/runtime are never modified.
_drop_route("/miniapp/consultation", "POST")
_drop_route("/miniapp/documents/generate", "POST")
_drop_route("/miniapp/parity", "GET")


@app.on_event("startup")
async def _business_startup() -> None:
    await init_consultation_store(settings)
    await init_document_payment_store(settings)


@app.on_event("shutdown")
async def _business_shutdown() -> None:
    await close_consultation_store()
    await close_document_payment_store()


def _quota_user_id(identity: str) -> int:
    try:
        return int(identity)
    except (TypeError, ValueError):
        # Stable negative id for explicitly enabled staging/dev auth. Real
        # Telegram WebApp identities are numeric and share quota with the agent.
        value = int(hashlib.sha256(str(identity).encode()).hexdigest()[:15], 16)
        return -(value or 1)


def _is_admin(identity: str) -> bool:
    try:
        return int(identity) in settings.admin_ids
    except (TypeError, ValueError):
        return False


def _require_admin(identity: str) -> None:
    if not _is_admin(identity):
        raise HTTPException(status_code=403, detail="Administrator access required")


def _payment_payload(order: ConsultationOrder) -> dict[str, Any]:
    return {
        "order_id": order.id,
        "amount_kzt": order.amount_kzt,
        "kaspi_url": settings.kaspi_payment_url,
        "status": order.status,
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
        "approval_required": True,
        "decision_note": order.decision_note,
        "receipt_accept": ["PDF", "JPG", "JPEG", "PNG", "WEBP"],
    }


def _document_admin_payload(order: DocumentPaymentOrder) -> dict[str, Any]:
    return {
        "order_id": order.id,
        "client_ref": order.user_key[:12],
        "case_id": order.case_id,
        "document_type": order.document_type,
        "language": order.language,
        "amount_kzt": order.amount_kzt,
        "status": order.status,
        "transaction_id": order.transaction_id,
        "receipt_check": order.receipt_check,
        "decision_note": order.decision_note,
    }


def _document_scope(case: dict[str, Any], document_type: str, language: str) -> str:
    # One payment authorizes one immutable factual scope. Any material or user
    # fact added after payment changes this digest and therefore requires a new
    # approval, matching the agent's request-scope semantics.
    context = core._case_context(case)
    value = f"{document_type}\n{language}\n{context}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()


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
        # paying again, matching the paid-consultation flow.
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
        "document_manual_confirmation": True,
        "document_payment_admin_configured": bool(settings.admin_ids),
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
        "document_manual_confirmation": True,
        "is_admin": _is_admin(identity),
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


@app.post("/miniapp/documents/generate")
async def generate_document(
    payload: core.GenerateRequest,
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    # When business payments are disabled, preserve the existing Mini App
    # behavior exactly. The Telegram agent is not involved in either path.
    if not settings.payments_enabled:
        return await core.generate_document(payload, x_telegram_init_data)

    if not settings.kaspi_payment_url.strip() or not settings.admin_ids:
        raise HTTPException(
            status_code=503,
            detail="Оплата документов временно недоступна: администратор или Kaspi не настроены. Подготовка документа не начата.",
        )

    identity = core.legacy._identity(x_telegram_init_data)
    state = await core.legacy._require_consent(identity)
    case = state["cases"].get(payload.case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    document_type = str(case.get("document_type") or payload.document_type or "claim")
    if document_type not in core._DOCUMENT_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported document type")
    language = "kk" if str(case.get("language") or payload.language) == "kk" else "ru"
    context = core._case_context(case)
    if not context.strip():
        raise HTTPException(status_code=422, detail="Добавьте описание ситуации или загрузите материалы дела")

    user_key = core.store.user_key(identity)
    scope = _document_scope(case, document_type, language)
    order = await get_scope_order(user_key=user_key, case_id=payload.case_id, case_fingerprint=scope)
    if order is None:
        order = await create_document_order(
            user_key=user_key,
            case_id=payload.case_id,
            case_fingerprint=scope,
            document_type=document_type,
            language=language,
            amount_kzt=settings.document_price_kzt,
        )

    if order.status != "approved":
        return {
            "payment_required": True,
            "generation_started": False,
            "payment": _document_payment_payload(order),
        }

    # The expensive legal research and Word generation starts only after a
    # human administrator has confirmed the real payment in Kaspi history.
    try:
        result = await core.generate_document(payload, x_telegram_init_data)
    except Exception:
        # Keep approval intact on a technical failure so the user can retry
        # without paying again.
        raise
    if not await consume_document_order(order.id, user_key=user_key):
        raise HTTPException(status_code=409, detail="Подтверждённая оплата уже использована для генерации")
    return {
        **result,
        "payment_required": False,
        "paid": True,
        "payment_order_id": order.id,
    }


@app.post("/miniapp/documents/payments/{order_id}/receipt")
async def document_payment_receipt(
    order_id: int,
    file: UploadFile = File(...),
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    identity = core.legacy._identity(x_telegram_init_data)
    await core.legacy._require_consent(identity)
    user_key = core.store.user_key(identity)
    order = await get_document_order(order_id, user_key=user_key)
    if order is None:
        raise HTTPException(status_code=404, detail="Платёжный запрос не найден")
    if order.status != "pending_receipt":
        raise HTTPException(status_code=409, detail="Чек по этому запросу уже передан на проверку или оплата уже подтверждена")

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
        raise HTTPException(status_code=502, detail="Не удалось выполнить предварительную проверку чека. Документ не разблокирован.") from exc

    # Document payments intentionally use the same policy as the agent:
    # obvious failures are rejected automatically, but AI never declares the
    # banking fact final. A human administrator must still compare Kaspi Pay.
    issues = receipt_hard_issues(check, order.amount_kzt)
    if issues:
        raise HTTPException(
            status_code=422,
            detail="Чек не прошёл предварительную проверку: " + "; ".join(issues[:6]),
        )

    accepted = await accept_document_receipt_precheck(
        order_id=order.id,
        user_key=user_key,
        receipt_hash=receipt_fingerprint(data),
        transaction_id=check.receipt_or_transaction_id,
        receipt_check=_receipt_check_payload(check),
    )
    if not accepted:
        raise HTTPException(status_code=409, detail="Этот чек/номер операции уже использовался или запрос уже обработан")

    updated = await get_document_order(order.id, user_key=user_key)
    assert updated is not None
    return {
        "ok": True,
        "payment_required": True,
        "generation_started": False,
        "payment": _document_payment_payload(updated),
        "message": "Чек прошёл предварительную проверку и ожидает ручного подтверждения администратора по Kaspi Pay.",
    }


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


@app.get("/miniapp/admin/document-payments")
async def admin_document_payments(
    status: str = "awaiting_admin",
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    identity = core.legacy._identity(x_telegram_init_data)
    await core.legacy._require_consent(identity)
    _require_admin(identity)
    orders = await list_document_orders_for_admin(status=status, limit=50)
    return {"orders": [_document_admin_payload(order) for order in orders]}


@app.post("/miniapp/admin/document-payments/{order_id}/decision")
async def admin_document_payment_decision(
    order_id: int,
    payload: AdminDocumentPaymentDecision,
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    identity = core.legacy._identity(x_telegram_init_data)
    await core.legacy._require_consent(identity)
    _require_admin(identity)
    order = await get_document_order(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Платёжный запрос не найден")
    if order.status != "awaiting_admin":
        raise HTTPException(status_code=409, detail="Этот платёжный запрос уже обработан")
    if not await decide_document_order(order.id, approved=payload.approved, note=payload.note):
        raise HTTPException(status_code=409, detail="Не удалось зафиксировать решение: статус уже изменился")
    updated = await get_document_order(order.id)
    assert updated is not None
    return {"ok": True, "order": _document_admin_payload(updated)}
