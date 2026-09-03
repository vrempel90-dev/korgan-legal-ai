from __future__ import annotations

import asyncio
import base64
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import Header, HTTPException

from korgan import miniapp_api_v5 as v5
from korgan import miniapp_document_payments as document_store
from korgan import miniapp_generation_jobs as jobs
from korgan.asgi_lifespan import add_lifespan
from korgan.miniapp_preliminary_delivery import client_notes
from korgan.payment_operation_lock import payment_operation_lock

LOGGER = logging.getLogger(__name__)
app = v5.app
core = v5.core
settings = v5.settings
_TASKS: dict[str, asyncio.Task[None]] = {}
_FREE_JOBS: dict[str, "FreeGenerationJob"] = {}
_FREE_CASE_JOB: dict[tuple[str, str], str] = {}
_HUMAN_TEXT = re.compile(r"[Ѐ-ӿ]")
_FREE_SCOPE_FIELD = "_free_generation_scope"
_FREE_JOB_FIELD = "_free_generation_job_id"

# The public promise is a one-to-two minute document. A provider request that
# outlives the complete document budget must not leave an immortal background
# job behind. The faster research/drafting policy normally finishes before this
# guard; the guard is the final containment boundary for provider stalls.
FREE_GENERATION_TIMEOUT_SECONDS = 120

_PAYMENT_REQUIRED_DETAIL = (
    "Подготовка документов доступна только после подтвержденной оплаты. "
    "Платежный контур временно не настроен, поэтому генерация не запущена."
)


@dataclass
class FreeGenerationJob:
    """Process-local job used only while the payment switch is off.

    Completed document metadata is also stored with the encrypted case, so a
    finished free document survives an application restart. In-flight work is
    deliberately not reported as durable: after a restart the client can start
    it again without a charge.
    """

    id: str
    identity: str
    case_id: str
    case_fingerprint: str
    document_type: str
    language: str
    status: str = "queued"
    stage: str = "queued"
    progress: int = 0
    error: str = ""


def _require_paid_document_runtime() -> None:
    """Reject operations that only make sense for an existing paid order."""
    if not settings.payments_enabled:
        raise HTTPException(status_code=503, detail=_PAYMENT_REQUIRED_DETAIL)


def _drop(path: str, method: str) -> None:
    wanted = method.upper()
    app.router.routes = [
        route
        for route in app.router.routes
        if not (
            getattr(route, "path", None) == path
            and wanted in (getattr(route, "methods", set()) or set())
        )
    ]


async def _startup() -> None:
    await jobs.init_generation_job_store(
        settings.database_url,
        enabled=settings.payments_enabled,
    )


async def _shutdown() -> None:
    tasks = list(_TASKS.values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _TASKS.clear()
    _FREE_JOBS.clear()
    _FREE_CASE_JOB.clear()
    await jobs.close_generation_job_store()


add_lifespan(app, startup=_startup, shutdown=_shutdown)


def _document_payload(case_id: str, case: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "status": case.get("status"),
        "title": case.get("title"),
        "verification_status": case.get("verification_status"),
        "verification_notes": list(case.get("verification_notes") or []),
        "quality_score": case.get("quality_score"),
        "quality_issues": list(case.get("quality_issues") or []),
        "filing_ready": bool(case.get("filing_ready")),
        "release_status": case.get("release_status"),
        "filename": case.get("filename"),
        # Единственный список, написанный для клиента: экран выпуска показывает
        # его, а не протокол гейтов.
        "todo_before_filing": client_notes(case),
    }


_MISSING_DOCUMENT_DETAIL = (
    "Задача завершена, но готовый документ не найден. "
    "Запустите восстановление без новой оплаты."
)


def _ready_document(state: dict[str, Any], case_id: str) -> dict[str, Any]:
    """Описание готового документа — или отказ признать задачу успешной.

    «Успешно» без сохранённого документа означало бы READY, за которым ничего
    нет: клиент показал бы кнопку скачивания файла, которого не существует.
    """
    case = (state.get("cases") or {}).get(case_id)
    if case is None or case.get("status") != "document_ready" or not case.get("document_base64"):
        raise HTTPException(status_code=409, detail=_MISSING_DOCUMENT_DETAIL)
    return _document_payload(case_id, case)


def _public_free_job(job: FreeGenerationJob) -> dict[str, Any]:
    return {
        "job_id": job.id,
        "case_id": job.case_id,
        "status": job.status,
        "stage": job.stage,
        "progress": max(0, min(int(job.progress), 100)),
        "document_ready": job.status == "succeeded",
        "retryable": job.status == "failed",
        "error": job.error if job.status == "failed" else "",
    }


def _free_client_error(exc: BaseException) -> str:
    if isinstance(exc, TimeoutError):
        return (
            "Подготовка превысила две минуты и безопасно остановлена. "
            "Повторите попытку — оплата не требуется."
        )
    detail = getattr(exc, "detail", "")
    message = str(detail or str(exc) or "").strip()
    if message and _HUMAN_TEXT.search(message):
        return message[:1000]
    return "Не удалось подготовить документ. Повторите попытку — оплата не требуется."


def _persisted_free_job(
    *,
    identity: str,
    case_id: str,
    case: dict[str, Any],
    case_fingerprint: str,
) -> FreeGenerationJob | None:
    """Rebuild the completed free job stored with an encrypted case."""
    if (
        case.get("status") != "document_ready"
        or not case.get("document_base64")
        or str(case.get(_FREE_SCOPE_FIELD) or "") != case_fingerprint
    ):
        return None
    job_id = str(case.get(_FREE_JOB_FIELD) or "").strip()
    if not job_id:
        return None
    return FreeGenerationJob(
        id=job_id,
        identity=identity,
        case_id=case_id,
        case_fingerprint=case_fingerprint,
        document_type=str(case.get("document_type") or "claim"),
        language="kk" if str(case.get("language")) == "kk" else "ru",
        status="succeeded",
        stage="completed",
        progress=100,
    )


def _remember_free_job(job: FreeGenerationJob) -> None:
    _FREE_JOBS[job.id] = job
    _FREE_CASE_JOB[(job.identity, job.case_id)] = job.id


async def _run_free_generation(job: FreeGenerationJob, *, context: str) -> None:
    job.status = "running"
    job.stage = "legal_research"
    job.progress = 20
    try:
        async with asyncio.timeout(FREE_GENERATION_TIMEOUT_SECONDS):
            draft, file_bytes, filename, meta = await core._generate(
                job.document_type,
                context,
                job.language,
            )
            job.stage = "quality_control"
            job.progress = 80

            # Imported here because the release runtime wraps the same core
            # during application assembly. Keeping the import lazy avoids a
            # circular import while preserving the final professional gate.
            from korgan.miniapp_professional_release import apply_release_policy

            payload = apply_release_policy(
                {
                    "status": "document_ready",
                    "title": getattr(draft, "title", "") or filename,
                    "verification_status": core._status_value(getattr(draft, "status", None)),
                    "verification_notes": list(meta["verification_notes"]),
                    "quality_score": meta["quality_score"],
                    "quality_issues": list(meta["quality_issues"]),
                    "filing_ready": bool(meta["filing_ready"]),
                    "release_status": str(meta["release_status"]),
                    "document_base64": base64.b64encode(file_bytes).decode("ascii"),
                    "filename": filename,
                },
                case_id=job.case_id,
            )
            job.stage = "document_render"
            job.progress = 90

            # Generation can take long enough for a user to add a material.
            # Never publish an old draft over a newer factual scope.
            state = await core.store.load(job.identity)
            case = (state.get("cases") or {}).get(job.case_id)
            if case is None:
                raise HTTPException(status_code=404, detail="Дело удалено во время подготовки документа")
            current_scope = v5.v4._document_scope(case, job.document_type, job.language)
            if current_scope != job.case_fingerprint:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Материалы дела изменились во время подготовки. "
                        "Запустите документ заново — оплата не требуется."
                    ),
                )

            case.update(payload)
            case[_FREE_SCOPE_FIELD] = job.case_fingerprint
            case[_FREE_JOB_FIELD] = job.id
            await core.store.save(job.identity, state)

        job.status = "succeeded"
        job.stage = "completed"
        job.progress = 100
        job.error = ""
        LOGGER.info(
            "FREE_DOCUMENT_COMPLETED case_id=%s document_type=%s",
            job.case_id,
            job.document_type,
        )
    except Exception as exc:
        job.status = "failed"
        job.stage = "failed"
        job.progress = 0
        job.error = _free_client_error(exc)
        LOGGER.exception(
            "FREE_DOCUMENT_FAILED case_id=%s document_type=%s",
            job.case_id,
            job.document_type,
        )
        raise


def _schedule_free_job(job: FreeGenerationJob, *, context: str) -> None:
    existing = _TASKS.get(job.id)
    if existing is not None and not existing.done():
        return
    task = asyncio.create_task(
        _run_free_generation(job, context=context),
        name=f"korgan-free-{job.id}",
    )
    _TASKS[job.id] = task

    def finished(done: asyncio.Task[None]) -> None:
        _consume_task_result(done)
        if _TASKS.get(job.id) is done:
            _TASKS.pop(job.id, None)

    task.add_done_callback(finished)


def _consume_task_result(task: asyncio.Task[None]) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception:
        # run_job already persisted and logged the failure. Retrieving the result
        # here prevents an unhandled-task warning without hiding the job status.
        pass


async def _schedule_job(
    *,
    job: jobs.GenerationJob,
    identity: str,
    document_type: str,
    context: str,
    language: str,
) -> None:
    existing = _TASKS.get(job.id)
    if existing is not None and not existing.done():
        return
    task = asyncio.create_task(
        jobs.run_job(
            job,
            identity=identity,
            store=core.store,
            document_type=document_type,
            context=context,
            language=language,
        ),
        name=f"korgan-generation-{job.id}",
    )
    _TASKS[job.id] = task

    def finished(done: asyncio.Task[None]) -> None:
        _consume_task_result(done)
        if _TASKS.get(job.id) is done:
            _TASKS.pop(job.id, None)

    task.add_done_callback(finished)


async def _generation_scope(
    payload: core.GenerateRequest,
    x_telegram_init_data: str,
) -> tuple[str, dict[str, Any], dict[str, Any], str, str, str, str]:
    identity = core.legacy._identity(x_telegram_init_data)
    state = await core.legacy._require_consent(identity)
    case = state.get("cases", {}).get(payload.case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")

    document_type = str(case.get("document_type") or payload.document_type or "claim")
    if document_type not in core._DOCUMENT_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported document type")
    if payload.document_type and payload.document_type != document_type:
        raise HTTPException(status_code=409, detail="Тип документа не соответствует активному делу")
    language = "kk" if str(case.get("language") or payload.language) == "kk" else "ru"
    context = core._case_context(case)
    if not context.strip():
        raise HTTPException(status_code=422, detail="Добавьте описание ситуации или загрузите материалы дела")
    user_key = core.store.user_key(identity)
    scope = v5.v4._document_scope(case, document_type, language)
    return identity, state, case, user_key, scope, document_type, language


async def _start_free_generation(
    *,
    identity: str,
    state: dict[str, Any],
    case: dict[str, Any],
    case_id: str,
    case_fingerprint: str,
    document_type: str,
    language: str,
) -> dict[str, Any]:
    """Start or recover the one free job for the current material scope."""
    persisted = _persisted_free_job(
        identity=identity,
        case_id=case_id,
        case=case,
        case_fingerprint=case_fingerprint,
    )
    if persisted is not None:
        _remember_free_job(persisted)
        return {
            "payment_required": False,
            "generation_started": False,
            "job": _public_free_job(persisted),
            "document": _ready_document(state, case_id),
        }

    key = (identity, case_id)
    old = _FREE_JOBS.get(_FREE_CASE_JOB.get(key, ""))
    if old is not None and old.case_fingerprint == case_fingerprint:
        if old.status in {"queued", "running"}:
            return {
                "payment_required": False,
                "generation_started": True,
                "job": _public_free_job(old),
            }
        if old.status == "succeeded":
            return {
                "payment_required": False,
                "generation_started": False,
                "job": _public_free_job(old),
                "document": _ready_document(state, case_id),
            }
    elif old is not None and old.status in {"queued", "running"}:
        raise HTTPException(
            status_code=409,
            detail=(
                "Материалы дела изменились во время уже запущенной подготовки. "
                "Дождитесь её завершения и запустите документ заново."
            ),
        )

    job = FreeGenerationJob(
        id=f"free-{uuid.uuid4()}",
        identity=identity,
        case_id=case_id,
        case_fingerprint=case_fingerprint,
        document_type=document_type,
        language=language,
    )
    _remember_free_job(job)
    _schedule_free_job(job, context=core._case_context(case))
    return {
        "payment_required": False,
        "generation_started": True,
        "job": _public_free_job(job),
    }


def _free_job_from_state(
    *,
    identity: str,
    state: dict[str, Any],
    job_id: str,
) -> FreeGenerationJob | None:
    job = _FREE_JOBS.get(job_id)
    if job is not None and job.identity == identity:
        return job
    for case_id, case in (state.get("cases") or {}).items():
        if str(case.get(_FREE_JOB_FIELD) or "") != job_id:
            continue
        scope = str(case.get(_FREE_SCOPE_FIELD) or "")
        rebuilt = _persisted_free_job(
            identity=identity,
            case_id=str(case_id),
            case=case,
            case_fingerprint=scope,
        )
        if rebuilt is not None:
            _remember_free_job(rebuilt)
            return rebuilt
    return None


async def _retry_free_generation(
    *,
    job_id: str,
    x_telegram_init_data: str,
) -> dict[str, Any]:
    identity = core.legacy._identity(x_telegram_init_data)
    state = await core.legacy._require_consent(identity)
    old = _free_job_from_state(identity=identity, state=state, job_id=job_id)
    if old is None:
        raise HTTPException(status_code=404, detail="Задача подготовки документа не найдена")
    if old.status != "failed":
        raise HTTPException(status_code=409, detail="Эту задачу нельзя запустить повторно")

    case = (state.get("cases") or {}).get(old.case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Дело для документа не найдено")
    payload = core.GenerateRequest(
        case_id=old.case_id,
        document_type=old.document_type,
        language=old.language,
    )
    resolved_identity, _, fresh_case, _, scope, document_type, language = await _generation_scope(
        payload,
        x_telegram_init_data,
    )
    if resolved_identity != identity:  # pragma: no cover - defensive adapter invariant
        raise HTTPException(status_code=403, detail="Недоступная задача подготовки документа")

    job = FreeGenerationJob(
        id=f"free-{uuid.uuid4()}",
        identity=identity,
        case_id=old.case_id,
        case_fingerprint=scope,
        document_type=document_type,
        language=language,
    )
    _remember_free_job(job)
    _schedule_free_job(job, context=core._case_context(fresh_case))
    return {
        "payment_required": False,
        "generation_started": True,
        "job": _public_free_job(job),
    }


# This is the final owner of generation. Payment gating remains in the same
# document-order store, while legal work is moved out of the request lifecycle.
_drop("/miniapp/documents/generate", "POST")


@app.post("/miniapp/documents/generate")
async def generate_document_job(
    payload: core.GenerateRequest,
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    if settings.payments_enabled and not settings.kaspi_payment_url.strip():
        raise HTTPException(status_code=503, detail="Kaspi-оплата временно не настроена. Документ не запущен.")

    identity, state, case, user_key, scope, document_type, language = await _generation_scope(
        payload,
        x_telegram_init_data,
    )
    if not settings.payments_enabled:
        return await _start_free_generation(
            identity=identity,
            state=state,
            case=case,
            case_id=payload.case_id,
            case_fingerprint=scope,
            document_type=document_type,
            language=language,
        )

    # Готовый документ за этот же состав материалов уже оплачен. Хранилище
    # платежей после списания переводит ордер в `consumed` и перестаёт находить
    # его как действующий, поэтому без этой проверки повторное нажатие создало
    # бы новый ордер и попросило заплатить второй раз за то, что уже есть.
    finished = await jobs.latest_job_for_case(
        user_key=user_key,
        case_id=payload.case_id,
        case_fingerprint=scope,
    )
    if finished is not None and finished.status == "succeeded":
        return {
            "payment_required": False,
            "generation_started": False,
            "job": jobs.public_job(finished),
            "document": _ready_document(state, payload.case_id),
        }

    async with payment_operation_lock(
        document_store._require_pool(),
        "miniapp-generation-start",
        f"{user_key}:{payload.case_id}",
    ):
        order = await document_store.get_scope_order(
            user_key=user_key,
            case_id=payload.case_id,
            case_fingerprint=scope,
        )
        if order is None:
            order = await document_store.create_document_order(
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
                "payment": v5._payment_payload(order),
            }

        job = await jobs.create_or_get_job(
            payment_order_id=order.id,
            user_key=user_key,
            case_id=payload.case_id,
            case_fingerprint=scope,
            document_type=document_type,
            language=language,
        )
        if job.status == "failed":
            return {
                "payment_required": False,
                "generation_started": False,
                "job": jobs.public_job(job),
            }
        if job.status == "queued":
            await _schedule_job(
                job=job,
                identity=identity,
                document_type=document_type,
                context=core._case_context(case),
                language=language,
            )
        return {
            "payment_required": False,
            "generation_started": job.status in {"queued", "running"},
            "job": jobs.public_job(job),
        }


@app.get("/miniapp/documents/generation/{job_id}")
async def generation_status(
    job_id: str,
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    identity = core.legacy._identity(x_telegram_init_data)
    state = await core.legacy._require_consent(identity)
    if not settings.payments_enabled:
        free_job = _free_job_from_state(identity=identity, state=state, job_id=job_id)
        if free_job is None:
            raise HTTPException(status_code=404, detail="Задача подготовки документа не найдена")
        result: dict[str, Any] = {"job": _public_free_job(free_job)}
        if free_job.status == "succeeded":
            result["document"] = _ready_document(state, free_job.case_id)
        return result

    user_key = core.store.user_key(identity)
    job = await jobs.require_job(job_id, user_key=user_key)
    result: dict[str, Any] = {"job": jobs.public_job(job)}
    if job.status == "succeeded":
        result["document"] = _ready_document(state, job.case_id)
    return result


@app.get("/miniapp/cases/{case_id}/generation")
async def case_generation_status(
    case_id: str,
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    """Что происходит с документом этого дела прямо сейчас.

    Дело переживает закрытие Mini App, а выданный при запуске `job_id` — нет.
    Поэтому опрос по делу и есть восстановление: после перезапуска клиента
    подготовка продолжает опрашиваться, а не начинается заново.
    """
    identity = core.legacy._identity(x_telegram_init_data)
    state = await core.legacy._require_consent(identity)
    case = (state.get("cases") or {}).get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    if not settings.payments_enabled:
        document_type = str(case.get("document_type") or "claim")
        language = "kk" if str(case.get("language")) == "kk" else "ru"
        current_scope = v5.v4._document_scope(case, document_type, language)
        free_job = _FREE_JOBS.get(_FREE_CASE_JOB.get((identity, case_id), ""))
        if free_job is None:
            free_job = _persisted_free_job(
                identity=identity,
                case_id=case_id,
                case=case,
                case_fingerprint=current_scope,
            )
            if free_job is not None:
                _remember_free_job(free_job)
        if free_job is None:
            return {"job": None}
        if free_job.case_fingerprint != current_scope and free_job.status not in {"queued", "running"}:
            return {"job": None}
        result: dict[str, Any] = {"job": _public_free_job(free_job)}
        if free_job.status == "succeeded":
            result["document"] = _ready_document(state, case_id)
        return result

    user_key = core.store.user_key(identity)
    job = await jobs.latest_job_for_case(user_key=user_key, case_id=case_id)
    if job is None:
        return {"job": None}
    result: dict[str, Any] = {"job": jobs.public_job(job)}
    if job.status == "succeeded":
        result["document"] = _ready_document(state, case_id)
    return result


@app.post("/miniapp/documents/generation/{job_id}/retry")
async def retry_generation(
    job_id: str,
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    if not settings.payments_enabled:
        return await _retry_free_generation(
            job_id=job_id,
            x_telegram_init_data=x_telegram_init_data,
        )
    _require_paid_document_runtime()
    identity = core.legacy._identity(x_telegram_init_data)
    state = await core.legacy._require_consent(identity)
    user_key = core.store.user_key(identity)
    existing = await jobs.require_job(job_id, user_key=user_key)
    order = await document_store.get_document_order(
        existing.payment_order_id,
        user_key=user_key,
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Платёжный запрос не найден")
    if order.status != "approved":
        raise HTTPException(status_code=409, detail="Оплата документа недоступна для повторной подготовки")
    case = state.get("cases", {}).get(existing.case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Дело для документа не найдено")
    current_scope = v5.v4._document_scope(case, order.document_type, order.language)
    if current_scope != order.case_fingerprint:
        raise HTTPException(
            status_code=409,
            detail="Материалы дела изменились. Повторно не платите; восстановите прежний состав дела или обратитесь в техподдержку.",
        )

    async with payment_operation_lock(
        document_store._require_pool(),
        "miniapp-generation-retry",
        existing.id,
    ):
        job = await jobs.reset_failed_job(existing.id)
        await _schedule_job(
            job=job,
            identity=identity,
            document_type=order.document_type,
            context=core._case_context(case),
            language=order.language,
        )
    return {
        "payment_required": False,
        "generation_started": True,
        "job": jobs.public_job(job),
    }


# У оплаченного документа должен быть один исполнитель. Прежний обработчик
# готовил документ прямо внутри запроса и списывал ту же оплату мимо блокировки
# задачи, поэтому повторное нажатие могло запустить вторую полную генерацию
# поверх уже идущей: две работы писали разные документы в одно дело, побеждал
# последний, а проигравший получал отказ уже после выполненной работы.
_drop("/miniapp/documents/payments/{order_id}/retry", "POST")


@app.post("/miniapp/documents/payments/{order_id}/retry")
async def retry_paid_document_job(
    order_id: int,
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    """Повторный запуск оплаченного документа — той же сохраняемой задачей."""
    _require_paid_document_runtime()

    identity = core.legacy._identity(x_telegram_init_data)
    state = await core.legacy._require_consent(identity)
    user_key = core.store.user_key(identity)
    order = await document_store.get_document_order(order_id, user_key=user_key)
    if order is None:
        raise HTTPException(status_code=404, detail="Платёжный запрос не найден")
    case = (state.get("cases") or {}).get(order.case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Дело для документа не найдено")
    # Без этой проверки запуск по изменившимся материалам не нашёл бы прежний
    # ордер по составу дела и попросил бы заплатить второй раз.
    if v5.v4._document_scope(case, order.document_type, order.language) != order.case_fingerprint:
        raise HTTPException(
            status_code=409,
            detail="Материалы дела изменились. Повторно не платите; восстановите прежний состав дела или обратитесь в техподдержку.",
        )

    job = await jobs.latest_job_for_case(
        user_key=user_key,
        case_id=order.case_id,
        case_fingerprint=order.case_fingerprint,
    )
    if job is not None and job.status == "failed":
        return await retry_generation(job.id, x_telegram_init_data=x_telegram_init_data)
    return await generate_document_job(
        core.GenerateRequest(
            case_id=order.case_id,
            document_type=order.document_type,
            language=order.language,
        ),
        x_telegram_init_data=x_telegram_init_data,
    )
