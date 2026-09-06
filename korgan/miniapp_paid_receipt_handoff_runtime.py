from __future__ import annotations

"""Durable payment -> generation handoff for every document payment path.

The Tole webhook already creates a persistent generation job. The legacy fiscal
receipt path historically generated the whole legal document inside the HTTP
request instead. This runtime makes both paths converge on the same durable,
idempotent worker without changing payment verification or charging semantics.
"""

import asyncio
import contextlib
import logging
from typing import Any

from fastapi import HTTPException

from korgan import miniapp_api_v5 as v5
from korgan import miniapp_document_payments as document_store
from korgan import miniapp_generation_api as generation_runtime
from korgan import miniapp_generation_jobs as jobs
from korgan import miniapp_paid_autostart_runtime as paid_runtime
from korgan import miniapp_payment_idempotency as idempotency
from korgan import miniapp_tole_payments as tole_runtime

LOGGER = logging.getLogger(__name__)
_INSTALLED = False
_RECOVERY_INTERVAL_SECONDS = 5.0
_RECOVERY_BATCH_SIZE = 5

_SCHEDULE_UNAVAILABLE = (
    "Оплата подтверждена и сохранена. Подготовку документа сейчас не удалось "
    "поставить в очередь — повторно платить не нужно, откройте дело через минуту."
)


async def _durable_run_approved_document(
    order: document_store.DocumentPaymentOrder,
    *,
    x_telegram_init_data: str,
) -> dict[str, Any]:
    """Return quickly after payment and let the server worker prepare the file.

    ``x_telegram_init_data`` deliberately is not used for generation. The paid
    order already stores the irreversible user key and immutable case scope, so
    the work can continue while Telegram is closed.
    """
    del x_telegram_init_data
    try:
        job = await paid_runtime.start_paid_generation(order.id)
    except Exception as exc:
        LOGGER.exception("PAID_DOCUMENT_SCHEDULE_UNAVAILABLE order_id=%s", order.id)
        raise HTTPException(status_code=503, detail=_SCHEDULE_UNAVAILABLE) from exc

    if job is None:
        raise HTTPException(status_code=503, detail=_SCHEDULE_UNAVAILABLE)

    return {
        "payment_required": False,
        "generation_started": job.status in {"queued", "running"},
        "job": jobs.public_job(job),
        "paid": True,
        "payment_confirmed": True,
        "payment_order_id": order.id,
        "payment": v5._payment_payload(order),
    }


async def _reconcile_all_paid_work() -> None:
    """Repair approval -> job gaps for Tole and fiscal-receipt orders alike."""
    if not generation_runtime.settings.payments_enabled:
        return

    # A killed worker becomes eligible for recovery only after the lease policy
    # says so. The deployed lease is already tied to the generation budget.
    await jobs.recover_interrupted_jobs(jobs._require_pool())

    rows = await document_store._require_pool().fetch(
        """
        SELECT o.id
        FROM korgan_miniapp_document_orders o
        LEFT JOIN korgan_miniapp_generation_jobs j ON j.payment_order_id=o.id
        WHERE o.status IN ('approved', 'consumed')
          AND (j.id IS NULL OR j.status='queued')
        ORDER BY o.id ASC
        LIMIT $1
        """,
        _RECOVERY_BATCH_SIZE,
    )
    for row in rows:
        try:
            await paid_runtime.start_paid_generation(int(row["id"]))
        except Exception:
            LOGGER.exception("Paid job scheduling unavailable order_id=%s", row["id"])

    # Tole reconciliation is still provider-specific. Run it only when the
    # provider is configured; fiscal-receipt orders need no external reconcile.
    if tole_runtime.tole_configured():
        try:
            await tole_runtime._ensure_schema()
            await tole_runtime._reconcile_pending_payments(limit=_RECOVERY_BATCH_SIZE)
        except Exception:
            LOGGER.exception("Paid payment reconciliation unavailable")


async def _fallback_reconciliation_loop() -> None:
    while True:
        try:
            await _reconcile_all_paid_work()
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Paid work recovery cycle failed")
        await asyncio.sleep(_RECOVERY_INTERVAL_SECONDS)


def _install_non_tole_recovery_worker() -> None:
    """Start a recovery loop when the older Tole-owned lifespan would not.

    ``miniapp_paid_autostart_runtime`` already starts its worker when Tole is
    configured. We replace its global reconcile function with the provider-
    neutral one above, so that existing worker now covers every paid order.
    When Tole is not configured, its lifespan intentionally starts no worker;
    this outer lifespan fills exactly that gap and does not create a duplicate.
    """
    app = generation_runtime.app
    previous = app.router.lifespan_context

    @contextlib.asynccontextmanager
    async def lifespan(scope_app: Any):
        async with previous(scope_app):
            worker: asyncio.Task[None] | None = None
            if generation_runtime.settings.payments_enabled and not tole_runtime.tole_configured():
                worker = asyncio.create_task(
                    _fallback_reconciliation_loop(),
                    name="korgan-paid-work-recovery-all-providers",
                )
            try:
                yield
            finally:
                if worker is not None:
                    worker.cancel()
                    await asyncio.gather(worker, return_exceptions=True)

    app.router.lifespan_context = lifespan


def install_paid_receipt_handoff_runtime() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    # ``v5._run_approved_document`` points to idempotency's locked wrapper.
    # Replacing its internal target keeps the payment lock and fresh-status
    # recheck intact while changing only the post-confirmation work from a long
    # HTTP request to the durable queue.
    idempotency._ORIGINAL_RUN_APPROVED_DOCUMENT = _durable_run_approved_document

    # The Tole lifespan calls this global at execution time, so replacing it is
    # enough to broaden an already-running recovery design to receipt payments.
    paid_runtime.reconcile_paid_work = _reconcile_all_paid_work
    _install_non_tole_recovery_worker()

    _INSTALLED = True
    LOGGER.info("Installed durable paid-document handoff for all payment paths")


install_paid_receipt_handoff_runtime()
