from __future__ import annotations

import asyncio
import base64
import hashlib
import time
from typing import Any

from fastapi import File, Header, HTTPException, UploadFile

from korgan import miniapp_api_v5 as v5

app = v5.app
core = v5.core
settings = v5.settings
payments = v5.payments
PARITY_REVISION = "2026-09-04.durable-generation-v6"

# One durable generation contract for every Mini App document type. The actual
# legal pipeline remains core._generate(), which already routes claim, contract,
# response, pretrial and pretrial_response through their production generators.
_TASKS: dict[str, asyncio.Task[None]] = {}


def _drop(path: str, method: str) -> None:
    v5._drop(path, method)


for _path, _method in (
    ("/miniapp/parity", "GET"),
    ("/miniapp/documents/generate", "POST"),
    ("/miniapp/documents/generation/{job_id}", "GET"),
    ("/miniapp/documents/generation/{job_id}/retry", "POST"),
    ("/miniapp/cases/{case_id}/generation", "GET"),
    ("/miniapp/documents/payments/{order_id}/receipt", "POST"),
    ("/miniapp/documents/payments/{order_id}", "GET"),
    ("/miniapp/documents/payments/{order_id}/retry", "POST"),
):
    _drop(_path, _method)


def _scope(case: dict[str, Any], document_type: str, language: str) -> str:
    return v5.v4._document_scope(case, document_type, language)


def _job_public(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": str(job.get("job_id") or ""),
        "case_id": str(job.get("case_id") or ""),
        "status": str(job.get("status") or "queued"),
        "stage": str(job.get("stage") or "queued"),
        "progress": int(job.get("progress") or 0),
        "document_ready": bool(job.get("document_ready")),
        "retryable": bool(job.get("retryable")),
        "error": str(job.get("error") or ""),
    }


def _document_public(case_id: str, case: dict[str, Any]) -> dict[str, Any] | None:
    encoded = str(case.get("document_base64") or "")
    filename = str(case.get("filename") or "").strip()
    if not encoded or not filename:
        return None
    return {
        "case_id": case_id,
        "status": str(case.get("status") or "document_ready"),
        "title": str(case.get("title") or filename),
        "verification_status": str(case.get("verification_status") or ""),
        "verification_notes": list(case.get("verification_notes") or []),
        "quality_score": case.get("quality_score"),
        "quality_issues": list(case.get("quality_issues") or []),
        "filing_ready": bool(case.get("filing_ready")),
        "release_status": str(case.get("release_status") or ""),
        "filename": filename,
        "document_base64": encoded,
    }


def _new_job_id(identity: str, case_id: str, scope: str) -> str:
    raw = f"{identity}:{case_id}:{scope}:{time.time_ns()}".encode("utf-8")
    return "GEN-" + hashlib.sha256(raw).hexdigest()[:20].upper()


async def _load_case(identity: str, case_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    state = await core.legacy._require_consent(identity)
    case = state.get("cases", {}).get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    return state, case


def _normalize_request(case: dict[str, Any], payload: core.GenerateRequest) -> tuple[str, str, str]:
    document_type = str(case.get("document_type") or payload.document_type or "claim").strip().lower()
    if document_type not in core._DOCUMENT_TYPES:
        raise HTTPException(status_code=400, detail="Неподдерживаемый тип документа")
    if payload.document_type and str(payload.document_type).strip().lower() != document_type:
        raise HTTPException(status_code=409, detail="Тип документа не соответствует активному делу")
    language = "kk" if str(case.get("language") or payload.language) == "kk" else "ru"
    if not core._case_context(case).strip():
        raise HTTPException(status_code=422, detail="Добавьте описание ситуации или загрузите материалы дела")
    return document_type, language, _scope(case, document_type, language)


async def _save_job(identity: str, case_id: str, job: dict[str, Any]) -> None:
    state, case = await _load_case(identity, case_id)
    case["generation_job"] = dict(job)
    await core.store.save(identity, state)


async def _set_job_fields(identity: str, case_id: str, job_id: str, **fields: Any) -> dict[str, Any] | None:
    state, case = await _load_case(identity, case_id)
    current = dict(case.get("generation_job") or {})
    if str(current.get("job_id") or "") != job_id:
        return None
    current.update(fields)
    case["generation_job"] = current
    await core.store.save(identity, state)
    return current


async def _run_job(identity: str, case_id: str, job_id: str) -> None:
    try:
        state, case = await _load_case(identity, case_id)
        job = dict(case.get("generation_job") or {})
        if str(job.get("job_id") or "") != job_id:
            return
        document_type = str(job.get("document_type") or "")
        language = str(job.get("language") or "ru")
        expected_scope = str(job.get("scope") or "")
        if _scope(case, document_type, language) != expected_scope:
            await _set_job_fields(
                identity,
                case_id,
                job_id,
                status="failed",
                stage="input_changed",
                progress=0,
                document_ready=False,
                retryable=False,
                error="Материалы дела изменились. Запустите подготовку документа заново по актуальным данным.",
            )
            return

        await _set_job_fields(
            identity,
            case_id,
            job_id,
            status="running",
            stage="legal_analysis",
            progress=15,
            document_ready=False,
            retryable=False,
            error="",
        )

        context = core._case_context(case)
        draft, file_bytes, filename, meta = await core._generate(document_type, context, language)

        # Never release a preliminary Word file. This duplicates the release
        # invariant of miniapp_professional_release for the background path,
        # because background generation intentionally calls core._generate().
        if not bool(meta.get("filing_ready")) or str(meta.get("release_status") or "") != "verified":
            issues = [str(x) for x in list(meta.get("quality_issues") or []) if str(x).strip()]
            notes = [str(x) for x in list(meta.get("verification_notes") or []) if str(x).strip()]
            reason = "; ".join((issues + notes)[:4])
            message = "Документ не прошёл финальную профессиональную проверку KORGAN. Повторная оплата не требуется."
            if reason:
                message += " Причина: " + reason
            await _set_job_fields(
                identity,
                case_id,
                job_id,
                status="failed",
                stage="quality_gate",
                progress=90,
                document_ready=False,
                retryable=True,
                error=message,
            )
            return

        # Reload immediately before release so concurrent uploads or edits cannot
        # make a document generated from stale facts downloadable.
        state, fresh_case = await _load_case(identity, case_id)
        current = dict(fresh_case.get("generation_job") or {})
        if str(current.get("job_id") or "") != job_id:
            return
        if _scope(fresh_case, document_type, language) != expected_scope:
            current.update({
                "status": "failed",
                "stage": "input_changed",
                "progress": 0,
                "document_ready": False,
                "retryable": False,
                "error": "Материалы дела изменились во время подготовки. Старый Word не выпущен.",
            })
            fresh_case["generation_job"] = current
            for key in ("document_base64", "filename"):
                fresh_case.pop(key, None)
            await core.store.save(identity, state)
            return

        current.update({
            "status": "succeeded",
            "stage": "completed",
            "progress": 100,
            "document_ready": True,
            "retryable": False,
            "error": "",
        })
        fresh_case.update({
            "status": "document_ready",
            "title": getattr(draft, "title", "") or filename,
            "verification_status": core._status_value(getattr(draft, "status", None)),
            "verification_notes": list(meta.get("verification_notes") or []),
            "quality_score": meta.get("quality_score"),
            "quality_issues": list(meta.get("quality_issues") or []),
            "filing_ready": True,
            "release_status": "verified",
            "document_base64": base64.b64encode(file_bytes).decode("ascii"),
            "filename": filename,
            "generation_job": current,
        })
        await core.store.save(identity, state)

        payment_order_id = int(current.get("payment_order_id") or 0)
        if payment_order_id and settings.payments_enabled:
            user_key = core.store.user_key(identity)
            # The document is already durably saved. Consumption is therefore
            # safe to retry after a process restart without losing a paid file.
            await payments.consume_document_order(payment_order_id, user_key=user_key)

    except asyncio.CancelledError:
        raise
    except Exception as exc:
        try:
            detail = getattr(exc, "detail", None)
            message = str(detail or exc or "Не удалось завершить подготовку документа")
            await _set_job_fields(
                identity,
                case_id,
                job_id,
                status="failed",
                stage="generation_error",
                progress=0,
                document_ready=False,
                retryable=True,
                error=message[:1000],
            )
        except Exception:
            pass
    finally:
        current = _TASKS.get(job_id)
        if current is asyncio.current_task():
            _TASKS.pop(job_id, None)


def _ensure_task(identity: str, case_id: str, job: dict[str, Any]) -> None:
    job_id = str(job.get("job_id") or "")
    if not job_id or str(job.get("status") or "") not in {"queued", "running"}:
        return
    existing = _TASKS.get(job_id)
    if existing is not None and not existing.done():
        return
    _TASKS[job_id] = asyncio.create_task(_run_job(identity, case_id, job_id), name=f"korgan-{job_id}")


async def _current_job(identity: str, case_id: str, expected_scope: str | None = None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    _, case = await _load_case(identity, case_id)
    job = dict(case.get("generation_job") or {})
    if not job.get("job_id"):
        return None, case
    if expected_scope is not None and str(job.get("scope") or "") != expected_scope:
        return None, case
    return job, case


async def _start_or_resume(
    identity: str,
    case_id: str,
    document_type: str,
    language: str,
    scope: str,
    *,
    payment_order_id: int = 0,
) -> dict[str, Any]:
    state, case = await _load_case(identity, case_id)
    existing = dict(case.get("generation_job") or {})
    if existing.get("job_id") and str(existing.get("scope") or "") == scope:
        status = str(existing.get("status") or "")
        if status in {"queued", "running", "succeeded", "failed"}:
            if payment_order_id and not int(existing.get("payment_order_id") or 0):
                existing["payment_order_id"] = payment_order_id
                case["generation_job"] = existing
                await core.store.save(identity, state)
            _ensure_task(identity, case_id, existing)
            return existing

    job = {
        "job_id": _new_job_id(identity, case_id, scope),
        "case_id": case_id,
        "document_type": document_type,
        "language": language,
        "scope": scope,
        "payment_order_id": int(payment_order_id or 0),
        "status": "queued",
        "stage": "queued",
        "progress": 5,
        "document_ready": False,
        "retryable": False,
        "error": "",
        "attempt": 1,
    }
    case["generation_job"] = job
    await core.store.save(identity, state)
    _ensure_task(identity, case_id, job)
    return job


async def _generation_response(identity: str, job: dict[str, Any]) -> dict[str, Any]:
    case_id = str(job.get("case_id") or "")
    _, case = await _load_case(identity, case_id)
    latest = dict(case.get("generation_job") or job)
    if str(latest.get("job_id") or "") != str(job.get("job_id") or ""):
        latest = job
    _ensure_task(identity, case_id, latest)

    if str(latest.get("status") or "") == "succeeded":
        document = _document_public(case_id, case)
        if document is None:
            latest = dict(latest)
            latest.update({
                "status": "failed",
                "stage": "delivery_error",
                "progress": 100,
                "document_ready": False,
                "retryable": True,
                "error": "Подготовка завершилась, но сохранённый Word не найден. Повторная оплата не требуется.",
            })
        else:
            payment_order_id = int(latest.get("payment_order_id") or 0)
            if payment_order_id and settings.payments_enabled:
                await payments.consume_document_order(payment_order_id, user_key=core.store.user_key(identity))
            return {"job": _job_public(latest), "document": document}
    return {"job": _job_public(latest), "document": None}


@app.get("/miniapp/parity")
async def parity() -> dict[str, Any]:
    payload = await v5.parity()
    payload.update({
        "parity_revision": PARITY_REVISION,
        "durable_document_generation": True,
        "document_generation_async": True,
        "document_generation_all_types": sorted(core._DOCUMENT_TYPES),
        "automatic_paid_generation": True,
    })
    return payload


@app.post("/miniapp/documents/generate")
async def generate_document(
    payload: core.GenerateRequest,
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    identity = core.legacy._identity(x_telegram_init_data)
    _, case = await _load_case(identity, payload.case_id)
    document_type, language, scope = _normalize_request(case, payload)

    # If a generation for this exact immutable factual scope already exists,
    # resume/return it before looking at payments. This makes retries idempotent
    # even after the paid order has already been consumed by a completed file.
    existing, _ = await _current_job(identity, payload.case_id, scope)
    if existing is not None:
        _ensure_task(identity, payload.case_id, existing)
        return await _generation_response(identity, existing)

    if not settings.payments_enabled:
        job = await _start_or_resume(identity, payload.case_id, document_type, language, scope)
        return await _generation_response(identity, job)

    if not settings.kaspi_payment_url.strip():
        raise HTTPException(status_code=503, detail="Kaspi-оплата временно не настроена. Документ не запущен.")

    user_key = core.store.user_key(identity)
    order = await payments.get_scope_order(user_key=user_key, case_id=payload.case_id, case_fingerprint=scope)
    if order is None:
        order = await payments.create_document_order(
            user_key=user_key,
            case_id=payload.case_id,
            case_fingerprint=scope,
            document_type=document_type,
            language=language,
            amount_kzt=settings.document_price_kzt,
        )
    order = await v5._auto_approve_stored(order, user_key=user_key)
    if order.status != "approved":
        return {
            "payment_required": True,
            "generation_started": False,
            "payment": v5._payment_payload(order),
        }

    job = await _start_or_resume(
        identity,
        payload.case_id,
        document_type,
        language,
        scope,
        payment_order_id=order.id,
    )
    result = await _generation_response(identity, job)
    return {**result, "payment_required": False, "paid": True, "payment_order_id": order.id}


@app.get("/miniapp/documents/generation/{job_id}")
async def generation_status(
    job_id: str,
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    identity = core.legacy._identity(x_telegram_init_data)
    state = await core.legacy._require_consent(identity)
    for case in state.get("cases", {}).values():
        job = dict(case.get("generation_job") or {})
        if str(job.get("job_id") or "") == job_id:
            return await _generation_response(identity, job)
    raise HTTPException(status_code=404, detail="Задача подготовки документа не найдена")


@app.get("/miniapp/cases/{case_id}/generation")
async def case_generation(
    case_id: str,
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    identity = core.legacy._identity(x_telegram_init_data)
    _, case = await _load_case(identity, case_id)
    job = dict(case.get("generation_job") or {})
    if not job.get("job_id"):
        return {"job": None, "document": None}
    document_type = str(job.get("document_type") or case.get("document_type") or "claim")
    language = "kk" if str(job.get("language") or case.get("language")) == "kk" else "ru"
    if str(job.get("scope") or "") != _scope(case, document_type, language):
        return {"job": None, "document": None}
    _ensure_task(identity, case_id, job)
    return await _generation_response(identity, job)


@app.post("/miniapp/documents/generation/{job_id}/retry")
async def retry_generation(
    job_id: str,
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    identity = core.legacy._identity(x_telegram_init_data)
    state = await core.legacy._require_consent(identity)
    for case_id, case in state.get("cases", {}).items():
        job = dict(case.get("generation_job") or {})
        if str(job.get("job_id") or "") != job_id:
            continue
        if str(job.get("status") or "") in {"queued", "running"}:
            _ensure_task(identity, case_id, job)
            return await _generation_response(identity, job)
        if str(job.get("status") or "") != "failed" or not bool(job.get("retryable")):
            raise HTTPException(status_code=409, detail="Эту подготовку нельзя повторить")
        document_type = str(job.get("document_type") or case.get("document_type") or "claim")
        language = "kk" if str(job.get("language") or case.get("language")) == "kk" else "ru"
        if str(job.get("scope") or "") != _scope(case, document_type, language):
            raise HTTPException(status_code=409, detail="Материалы дела изменились. Запустите новый документ по актуальным данным.")
        job.update({
            "status": "queued",
            "stage": "queued",
            "progress": 5,
            "document_ready": False,
            "retryable": False,
            "error": "",
            "attempt": int(job.get("attempt") or 1) + 1,
        })
        case["generation_job"] = job
        await core.store.save(identity, state)
        _ensure_task(identity, case_id, job)
        return await _generation_response(identity, job)
    raise HTTPException(status_code=404, detail="Задача подготовки документа не найдена")


async def _start_paid_order(order: Any, x_telegram_init_data: str) -> tuple[str, dict[str, Any]]:
    identity = core.legacy._identity(x_telegram_init_data)
    _, case = await _load_case(identity, order.case_id)
    payload = core.GenerateRequest(
        case_id=order.case_id,
        document_type=order.document_type,
        language=order.language,
    )
    document_type, language, scope = _normalize_request(case, payload)
    if scope != order.case_fingerprint:
        raise HTTPException(
            status_code=409,
            detail="Материалы дела изменились после оплаты. Повторно не платите; обратитесь в техподдержку для восстановления оплаченного состава дела.",
        )
    job = await _start_or_resume(
        identity,
        order.case_id,
        document_type,
        language,
        scope,
        payment_order_id=order.id,
    )
    return identity, job


@app.post("/miniapp/documents/payments/{order_id}/receipt")
async def document_payment_receipt(
    order_id: int,
    file: UploadFile = File(...),
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    # Reuse v5's strict Kaspi receipt verification. Only the post-approval action
    # changes: generation is started immediately instead of exposing a manual
    # "prepare paid document" step.
    verified = await v5.document_payment_receipt(order_id, file, x_telegram_init_data)
    identity = core.legacy._identity(x_telegram_init_data)
    user_key = core.store.user_key(identity)
    order = await payments.get_document_order(order_id, user_key=user_key)
    if order is None:
        raise HTTPException(status_code=404, detail="Платёжный запрос не найден")
    order = await v5._auto_approve_stored(order, user_key=user_key)
    if order.status != "approved":
        return verified

    identity, job = await _start_paid_order(order, x_telegram_init_data)
    result = await _generation_response(identity, job)
    return {
        **result,
        "ok": True,
        "payment_required": False,
        "generation_started": True,
        "payment": v5._payment_payload(order),
        "message": "Оплата прошла. Документ разблокирован и уже генерируется.",
    }


@app.get("/miniapp/documents/payments/{order_id}")
async def document_payment_status(
    order_id: int,
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    identity = core.legacy._identity(x_telegram_init_data)
    await core.legacy._require_consent(identity)
    user_key = core.store.user_key(identity)
    order = await payments.get_document_order(order_id, user_key=user_key)
    if order is None:
        raise HTTPException(status_code=404, detail="Платёжный запрос не найден")
    order = await v5._auto_approve_stored(order, user_key=user_key)

    result: dict[str, Any] = {}
    if order.status == "approved":
        identity, job = await _start_paid_order(order, x_telegram_init_data)
        result = await _generation_response(identity, job)
    elif order.status == "consumed":
        existing, case = await _current_job(identity, order.case_id)
        if existing is not None and int(existing.get("payment_order_id") or 0) == order.id:
            result = await _generation_response(identity, existing)

    payment_payload = v5._payment_payload(order)
    # A consumed order with its own durable job is still presented as approved
    # to legacy UI code until it transitions into the generation/ready screen.
    if order.status == "consumed" and result.get("job"):
        payment_payload = {**payment_payload, "status": "approved"}
    return {"payment": payment_payload, **result}


@app.post("/miniapp/documents/payments/{order_id}/retry")
async def retry_paid_document(
    order_id: int,
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    identity = core.legacy._identity(x_telegram_init_data)
    await core.legacy._require_consent(identity)
    user_key = core.store.user_key(identity)
    order = await payments.get_document_order(order_id, user_key=user_key)
    if order is None:
        raise HTTPException(status_code=404, detail="Платёжный запрос не найден")
    order = await v5._auto_approve_stored(order, user_key=user_key)
    existing, _ = await _current_job(identity, order.case_id)
    if existing is not None and int(existing.get("payment_order_id") or 0) == order.id:
        if str(existing.get("status") or "") == "failed" and bool(existing.get("retryable")):
            return await retry_generation(str(existing.get("job_id")), x_telegram_init_data)
        return await _generation_response(identity, existing)
    if order.status != "approved":
        raise HTTPException(status_code=409, detail="Оплата ещё не подтверждена")
    identity, job = await _start_paid_order(order, x_telegram_init_data)
    return await _generation_response(identity, job)
