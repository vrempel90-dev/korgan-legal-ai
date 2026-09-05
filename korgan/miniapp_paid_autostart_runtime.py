from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from korgan import miniapp_api_v5 as v5
from korgan import miniapp_document_payments as document_store
from korgan import miniapp_generation_api as generation_runtime
from korgan import miniapp_generation_jobs as jobs
from korgan import miniapp_tole_payments as tole_runtime

LOGGER = logging.getLogger(__name__)

_INSTALLED = False
_ORIGINAL_APPROVE = tole_runtime._approve_order_from_tole
_AUTO_TASKS: dict[str, asyncio.Task[None]] = {}
_RECONCILE_INTERVAL_SECONDS = 5.0
_RECONCILE_BATCH_SIZE = 5

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
    consent = state.get("consent")
    if not isinstance(consent, dict) or not consent.get("accepted"):
        raise jobs.GenerationFailure("Для подготовки документа требуется согласие на обработку материалов.")
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
    async def on_stage(stage: str, progress: int) -> None:
        await jobs.update_job(
            job.id,
            status="running",
            stage=stage,
            progress=progress,
        )

    if await jobs.claim_job(job.id) is None:
        LOGGER.info("Paid autostart job already claimed job_id=%s order_id=%s", job.id, order.id)
        return

    heartbeat = asyncio.create_task(
        jobs._heartbeat(job.id),
        name=f"korgan-paid-autostart-heartbeat-{job.id}",
    )
    try:
        await on_stage("starting", 5)
        result = await jobs._generate_payload(
            order.document_type,
            context,
            order.language,
            case_id=order.case_id,
            on_stage=on_stage,
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


async def reconcile_paid_work() -> None:
    """Repair payment -> job gaps even when every client WebView is closed.

    Approved orders are themselves the durable work queue. If the process dies
    between saving approval and inserting a job, the next cycle finds the order.
    A unique payment_order_id plus claim_job's database transition owns execution.
    Failed legal work is not retried blindly; its findings remain available.
    """
    if not generation_runtime.settings.payments_enabled or not tole_runtime.tole_configured():
        return
    await tole_runtime._ensure_schema()
    # Startup may happen before an interrupted job's lease expires. Revisit
    # silent running jobs, but leave queued jobs available for rescheduling.
    await jobs.recover_interrupted_jobs(jobs._require_pool())
    rows = await document_store._require_pool().fetch(
        """
        SELECT o.id
        FROM korgan_miniapp_document_orders o
        JOIN korgan_miniapp_tole_payments t ON t.order_id=o.id
        LEFT JOIN korgan_miniapp_generation_jobs j ON j.payment_order_id=o.id
        WHERE o.status IN ('approved', 'consumed')
          AND (j.id IS NULL OR j.status='queued')
        ORDER BY o.id ASC
        LIMIT $1
        """,
        _RECONCILE_BATCH_SIZE,
    )
    for row in rows:
        try:
            await start_paid_generation(int(row["id"]))
        except Exception:
            LOGGER.exception("Paid job scheduling unavailable order_id=%s", row["id"])
    # Repair already-approved work before waiting on the external provider.
    try:
        await tole_runtime._reconcile_pending_payments(limit=_RECONCILE_BATCH_SIZE)
    except Exception:
        LOGGER.exception("Paid payment reconciliation unavailable")


async def _reconciliation_loop() -> None:
    while True:
        try:
            await reconcile_paid_work()
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Paid work recovery cycle failed")
        await asyncio.sleep(_RECONCILE_INTERVAL_SECONDS)


def _install_background_lifespan() -> None:
    app = generation_runtime.app
    previous = app.router.lifespan_context

    @contextlib.asynccontextmanager
    async def lifespan(scope_app: Any):
        # All state/payment/job stores must be open before the worker starts;
        # cancel its work before the earlier lifespan closes those stores.
        async with previous(scope_app):
            worker = None
            if generation_runtime.settings.payments_enabled and tole_runtime.tole_configured():
                worker = asyncio.create_task(_reconciliation_loop(), name="korgan-paid-work-recovery")
            try:
                yield
            finally:
                tasks = list(_AUTO_TASKS.values())
                if worker is not None:
                    tasks.append(worker)
                for task in tasks:
                    task.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                _AUTO_TASKS.clear()

    app.router.lifespan_context = lifespan


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
    global _INSTALLED
    if _INSTALLED:
        return
    tole_runtime._approve_order_from_tole = _approve_and_autostart  # type: ignore[assignment]
    _install_background_lifespan()
    _INSTALLED = True
    LOGGER.info("Installed Tole paid-document autostart runtime")


install_paid_autostart_runtime()
