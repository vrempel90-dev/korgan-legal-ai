from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import HTTPException

from korgan import generation_progress as progress
from korgan import miniapp_api_v5 as v5
from korgan import miniapp_document_payments as document_store
from korgan import miniapp_generation_api as generation_runtime
from korgan import miniapp_generation_jobs as jobs
from korgan import miniapp_tole_payments as tole_runtime

LOGGER = logging.getLogger(__name__)

_INSTALLED = False
_ORIGINAL_APPROVE = tole_runtime._approve_order_from_tole
_AUTO_TASKS: dict[str, asyncio.Task[None]] = {}

_SCOPE_CHANGED = (
    "Материалы дела изменились после создания оплаты. Повторно не платите: "
    "KORGAN не начал документ по другому составу фактов."
)
_MISSING_CASE = (
    "После оплаты KORGAN не нашёл исходное дело. Повторно не платите; "
    "обратитесь в поддержку для восстановления документа."
)


def _consume_task_result(task: asyncio.Task[None]) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception:
        # Status and client-safe detail are persisted by _run_paid_job.
        pass


async def _mark_failed(job: jobs.GenerationJob, detail: str) -> None:
    await jobs.update_job(
        job.id,
        status="failed",
        stage="failed",
        progress=0,
        error_detail=detail,
    )


async def _load_paid_case(order: document_store.DocumentPaymentOrder) -> tuple[dict[str, Any], dict[str, Any], str]:
    state = await generation_runtime.core.store.load_by_user_key(order.user_key)
    case = (state.get("cases") or {}).get(order.case_id)
    if case is None:
        raise jobs.GenerationFailure(_MISSING_CASE)

    current_scope = v5.v4._document_scope(case, order.document_type, order.language)
    if current_scope != order.case_fingerprint:
        raise jobs.GenerationFailure(_SCOPE_CHANGED)

    context = generation_runtime.core._case_context(case)
    if not str(context or "").strip():
        raise jobs.GenerationFailure(
            "После оплаты в деле нет исходных материалов для документа. "
            "Повторно не платите; восстановите материалы дела."
        )
    return state, case, context


async def _run_paid_job(
    job: jobs.GenerationJob,
    *,
    order: document_store.DocumentPaymentOrder,
    context: str,
) -> None:
    async def on_stage(stage: str, value: int) -> None:
        await jobs.update_job(
            job.id,
            status="running",
            stage=stage,
            progress=value,
        )

    if await jobs.claim_job(job.id) is None:
        LOGGER.info("Paid autostart job already claimed job_id=%s order_id=%s", job.id, order.id)
        return

    heartbeat = asyncio.create_task(
        jobs._heartbeat(job.id),
        name=f"korgan-paid-autostart-heartbeat-{job.id}",
    )
    # Тот же приёмник стадий, что и у обычного запуска: конвейер зовёт его
    # синхронно, поэтому собственная async-версия здесь только теряла бы стадии.
    report_stage = jobs.StageReporter(job.id)
    try:
        await on_stage(progress.STARTING, progress.progress_for(progress.STARTING))
        result = await jobs._generate_payload(
            order.document_type,
            context,
            order.language,
            case_id=order.case_id,
            report_stage=report_stage,
        )

        # Re-read the encrypted case before publishing. Payment authorizes only
        # the exact fingerprint that existed when the order was created; facts
        # added or removed while AI was drafting must never be silently mixed
        # into the paid document.
        state, case, _ = await _load_paid_case(order)

        await jobs._claim_payment(job)
        case.update(result)
        await generation_runtime.core.store.save_by_user_key(order.user_key, state)
        await jobs.update_job(
            job.id,
            status="succeeded",
            stage="completed",
            progress=100,
        )
        LOGGER.info("PAID_DOCUMENT_AUTOSTART_COMPLETED order_id=%s job_id=%s", order.id, job.id)
    except Exception as exc:
        await jobs.update_job(
            job.id,
            status="failed",
            stage="failed",
            progress=0,
            error_detail=jobs._client_detail(exc),
        )
        LOGGER.exception("PAID_DOCUMENT_AUTOSTART_FAILED order_id=%s job_id=%s", order.id, job.id)
        raise
    finally:
        heartbeat.cancel()
        await asyncio.gather(heartbeat, return_exceptions=True)
        await report_stage.flush()


async def start_paid_generation(order_id: int) -> jobs.GenerationJob | None:
    """Create and schedule the single durable job immediately after payment.

    No Telegram initData is needed here. The payment order already contains the
    non-reversible HMAC user key and immutable case fingerprint; the encrypted
    Mini App store can therefore load the exact paid case server-side without
    persisting or recovering the Telegram user id.
    """
    order = await document_store.get_document_order(int(order_id))
    if order is None or order.status not in {"approved", "consumed"}:
        return None

    job = await jobs.create_or_get_job(
        payment_order_id=order.id,
        user_key=order.user_key,
        case_id=order.case_id,
        case_fingerprint=order.case_fingerprint,
        document_type=order.document_type,
        language=order.language,
    )
    if job.status in {"running", "succeeded", "failed"}:
        return job

    try:
        _, _, context = await _load_paid_case(order)
    except jobs.GenerationFailure as exc:
        await _mark_failed(job, str(exc))
        return await jobs.require_job(job.id, user_key=order.user_key)

    existing = _AUTO_TASKS.get(job.id)
    if existing is not None and not existing.done():
        return job

    task = asyncio.create_task(
        _run_paid_job(job, order=order, context=context),
        name=f"korgan-paid-autostart-{job.id}",
    )
    _AUTO_TASKS[job.id] = task

    def finished(done: asyncio.Task[None]) -> None:
        _consume_task_result(done)
        if _AUTO_TASKS.get(job.id) is done:
            _AUTO_TASKS.pop(job.id, None)

    task.add_done_callback(finished)
    LOGGER.info("PAID_DOCUMENT_AUTOSTART_SCHEDULED order_id=%s job_id=%s", order.id, job.id)
    return job


_SCHEDULE_UNAVAILABLE = (
    "Оплата подтверждена и сохранена. Подготовку документа сейчас не удалось "
    "поставить в очередь — повторно платить не нужно, откройте дело через минуту."
)


async def _durable_run_approved_document(
    order: document_store.DocumentPaymentOrder,
    *,
    x_telegram_init_data: str,
) -> dict[str, Any]:
    """Подтверждённая оплата ставит задачу в очередь, а не готовит документ здесь.

    Прежний обработчик вызывал юридический конвейер прямо внутри HTTP-запроса.
    Подготовка занимает около двух минут, поэтому запрос жил на грани таймаута
    Telegram WebView и прокси, а строки задачи не существовало вовсе: показать
    прогресс было нечем, закрытие Mini App теряло работу, и оборванный запрос
    выглядел для клиента как «Сервис временно недоступен» при списанной оплате.

    Здесь оба платёжных провайдера сходятся в одну сохраняемую задачу. Ответ
    несёт и её состояние, и сам платёж: экран оплаты разбирает именно `payment`,
    а экран подготовки — `job`.

    ``x_telegram_init_data`` не используется: задача находит оплаченное дело по
    необратимому ключу пользователя из самого ордера, поэтому подготовка не
    зависит ни от подписи Telegram, ни от того, вернулся ли человек в Mini App.
    """
    try:
        job = await start_paid_generation(order.id)
    except Exception as exc:  # noqa: BLE001 — оплата уже подтверждена и сохранена
        # Имя недоступного хранилища ничего не объясняет человеку и не должно
        # доходить до экрана. Причина остаётся в журнале, ордер — оплаченным.
        LOGGER.exception("PAID_DOCUMENT_SCHEDULE_UNAVAILABLE order_id=%s", order.id)
        raise HTTPException(status_code=503, detail=_SCHEDULE_UNAVAILABLE) from exc
    if job is None:
        raise HTTPException(status_code=503, detail=_SCHEDULE_UNAVAILABLE)
    return {
        "payment_required": False,
        "generation_started": job.status in {"queued", "running"},
        "job": jobs.public_job(job),
        "paid": True,
        "payment_order_id": order.id,
        "payment": v5._payment_payload(order),
    }


async def _approve_and_autostart(order_id: int, *, provider_intent_id: str) -> None:
    await _ORIGINAL_APPROVE(order_id, provider_intent_id=provider_intent_id)
    try:
        await start_paid_generation(order_id)
    except Exception:
        # Payment acknowledgement must remain idempotently successful even when
        # generation scheduling has an infrastructure problem. The approved
        # order stays paid and retryable; polling/reconciliation calls this same
        # wrapper again and gets another chance to schedule without a new charge.
        LOGGER.exception("PAID_DOCUMENT_AUTOSTART_SCHEDULE_ERROR order_id=%s", order_id)


def install_paid_autostart_runtime() -> None:
    """Подключить сохраняемую подготовку к обоим способам подтверждения оплаты.

    Заменяется не внешний `v5._run_approved_document`, а тот внутренний
    обработчик, который вызывает слой идемпотентности: блокировка платежа и
    перепроверка статуса ордера остаются на месте, меняется только то, что
    происходит после подтверждения — очередь вместо работы внутри запроса.
    """
    global _INSTALLED
    if _INSTALLED:
        return
    from korgan import miniapp_payment_idempotency as idempotency

    tole_runtime._approve_order_from_tole = _approve_and_autostart  # type: ignore[assignment]
    idempotency._ORIGINAL_RUN_APPROVED_DOCUMENT = _durable_run_approved_document  # type: ignore[assignment]
    _INSTALLED = True
    LOGGER.info("Installed paid-document autostart runtime for Tole and fiscal-receipt confirmation")


install_paid_autostart_runtime()
