from __future__ import annotations

import asyncio
import logging
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


# This is the final owner of generation. Payment gating remains in the same
# document-order store, while legal work is moved out of the request lifecycle.
_drop("/miniapp/documents/generate", "POST")


@app.post("/miniapp/documents/generate")
async def generate_document_job(
    payload: core.GenerateRequest,
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    if not settings.payments_enabled:
        # The development/free mode has no PostgreSQL payment order to bind a
        # durable job to, so preserve the already-tested synchronous behavior.
        return await core.generate_document(payload, x_telegram_init_data)
    if not settings.kaspi_payment_url.strip():
        raise HTTPException(status_code=503, detail="Kaspi-оплата временно не настроена. Документ не запущен.")

    identity, state, case, user_key, scope, document_type, language = await _generation_scope(
        payload,
        x_telegram_init_data,
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
    if case_id not in (state.get("cases") or {}):
        raise HTTPException(status_code=404, detail="Case not found")
    if not settings.payments_enabled:
        # Бесплатный режим готовит документ внутри запроса и хранилище задач не
        # поднимает: незавершённых задач там не бывает по построению.
        return {"job": None}

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
    if not settings.payments_enabled:
        # Бесплатный режим готовит документ внутри запроса и платёжных ордеров
        # не заводит: повторять по номеру оплаты здесь нечего.
        raise HTTPException(status_code=404, detail="Платёжный запрос не найден")

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
