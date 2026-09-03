from __future__ import annotations

import logging
from typing import Any

from fastapi import Header, HTTPException

from korgan import miniapp_api_v5 as v5
from korgan import miniapp_document_payments as document_store
from korgan import miniapp_generation_api as generation_runtime
from korgan import miniapp_generation_jobs as jobs
from korgan import miniapp_paid_autostart_runtime as autostart_runtime
from korgan import miniapp_tole_payments as tole_runtime
from korgan.payment_operation_lock import payment_operation_lock

LOGGER = logging.getLogger(__name__)

app = tole_runtime.app
core = tole_runtime.core
settings = tole_runtime.settings
_INSTALLED = False

_PAYMENT_DISABLED = (
    "Оплата документов временно отключена. Новая оплата не создаётся и генерация "
    "не запускается. Уже подтверждённый платёж сохраняется; повторно платить не нужно."
)


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


async def _refresh_order(order: document_store.DocumentPaymentOrder) -> document_store.DocumentPaymentOrder:
    refreshed = await document_store.get_document_order(order.id, user_key=order.user_key)
    return refreshed or order


async def _reconcile_existing_payment(order: document_store.DocumentPaymentOrder) -> tuple[document_store.DocumentPaymentOrder, Any]:
    payment = await tole_runtime._get_tole_payment(order.id)
    if payment is None:
        return order, None
    if order.status == "pending_receipt":
        try:
            payment = await tole_runtime._reconcile_payment(payment)
        except tole_runtime.ToleAPIError:
            # A provider timeout must not destroy a durable order or create a new
            # one. The same idempotent payment intent remains available for the
            # next webhook/poll.
            LOGGER.warning("TOLE_STATUS_UNAVAILABLE order_id=%s", order.id)
        order = await _refresh_order(order)
    return order, payment


async def _generation_result(identity: str, order: document_store.DocumentPaymentOrder) -> dict[str, Any]:
    job = await jobs.latest_job_for_case(
        user_key=order.user_key,
        case_id=order.case_id,
        case_fingerprint=order.case_fingerprint,
    )
    if job is None and order.status in {"approved", "consumed"}:
        job = await autostart_runtime.start_paid_generation(order.id)

    if job is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Оплата подтверждена, но задача подготовки ещё не создана. "
                "Повторно платить не нужно; повторите проверку через несколько секунд."
            ),
        )

    result: dict[str, Any] = {
        "payment_required": False,
        "generation_started": job.status in {"queued", "running"},
        "job": jobs.public_job(job),
    }
    if job.status == "succeeded":
        state = await core.legacy._require_consent(identity)
        result["document"] = generation_runtime._ready_document(state, order.case_id)
    return result


def install_payment_hardening_runtime() -> None:
    """Make Tole -> generation a single durable state machine.

    The old Tole route delegated an approved payment back into the legacy
    generation endpoint. That endpoint still required KASPI_PAYMENT_URL even
    though Tole already owned payment creation, producing a false 503 after a
    real paid event. These replacement routes never infer payment state from UI
    or legacy Kaspi settings: provider state, payment order and generation job
    are read from durable server stores only.
    """
    global _INSTALLED
    if _INSTALLED or not tole_runtime.tole_configured():
        return

    _drop("/miniapp/documents/generate", "POST")
    _drop("/miniapp/documents/payments/{order_id}", "GET")
    _drop("/miniapp/documents/generation/{job_id}/retry", "POST")

    @app.post("/miniapp/documents/generate")
    async def hardened_generate_document(
        payload: core.GenerateRequest,
        x_telegram_init_data: str = Header(default=""),
    ) -> dict[str, Any]:
        # PAYMENTS_ENABLED is the production kill switch. It blocks creation of
        # new payment intents and legal work while the payment system is under
        # maintenance; it must never become a free-generation switch.
        if not settings.payments_enabled:
            raise HTTPException(status_code=503, detail=_PAYMENT_DISABLED)

        tole_runtime._require_tole_runtime()
        identity, order = await tole_runtime._resolve_document_order(payload, x_telegram_init_data)
        order, payment = await _reconcile_existing_payment(order)

        if order.status in {"approved", "consumed"}:
            return await _generation_result(identity, order)

        if order.status != "pending_receipt":
            raise HTTPException(
                status_code=409,
                detail=(
                    "Предыдущая попытка оплаты закрыта. Новый платёж не будет создан автоматически. "
                    "Обновите дело и повторите действие; повторно не платите, если деньги уже списались."
                ),
            )

        # A payment intent is reserved by order id and protected by provider
        # idempotency, so retries cannot create parallel charges for one scope.
        try:
            payment = await tole_runtime._ensure_tole_qr(order)
        except tole_runtime.ToleAPIError as exc:
            LOGGER.warning(
                "TOLE_QR_CREATE_FAILED order_id=%s status=%s kind=%s",
                order.id,
                exc.status_code,
                exc.kind,
            )
            raise HTTPException(
                status_code=502,
                detail="Не удалось создать оплату Tole. Повторно платить не нужно; повторите попытку позже.",
            ) from exc

        order = await _refresh_order(order)
        if not payment.payment_url:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Tole ещё создаёт ссылку оплаты. Повторите через несколько секунд; "
                    "новая платёжная заявка не создастся."
                ),
            )
        return {
            "payment_required": True,
            "generation_started": False,
            "payment": tole_runtime._payment_payload(order, payment),
        }

    @app.get("/miniapp/documents/payments/{order_id}")
    async def hardened_document_payment_status(
        order_id: int,
        x_telegram_init_data: str = Header(default=""),
    ) -> dict[str, Any]:
        identity = core.legacy._identity(x_telegram_init_data)
        await core.legacy._require_consent(identity)
        user_key = core.store.user_key(identity)
        order = await document_store.get_document_order(order_id, user_key=user_key)
        if order is None:
            raise HTTPException(status_code=404, detail="Платёжный запрос не найден")

        order, payment = await _reconcile_existing_payment(order)
        result: dict[str, Any] = {"payment": tole_runtime._payment_payload(order, payment)}

        # The payment screen can recover a server-side autostart after a webhook
        # race without issuing a second generation command or creating a second
        # order. Extra fields are additive and safe for older clients.
        if order.status in {"approved", "consumed"}:
            job = await jobs.latest_job_for_case(
                user_key=order.user_key,
                case_id=order.case_id,
                case_fingerprint=order.case_fingerprint,
            )
            if job is None and settings.payments_enabled:
                job = await autostart_runtime.start_paid_generation(order.id)
            if job is not None:
                result["job"] = jobs.public_job(job)
                if job.status == "succeeded":
                    state = await core.legacy._require_consent(identity)
                    result["document"] = generation_runtime._ready_document(state, order.case_id)
        return result

    @app.post("/miniapp/documents/generation/{job_id}/retry")
    async def hardened_retry_generation(
        job_id: str,
        x_telegram_init_data: str = Header(default=""),
    ) -> dict[str, Any]:
        if not settings.payments_enabled:
            raise HTTPException(status_code=503, detail=_PAYMENT_DISABLED)

        identity = core.legacy._identity(x_telegram_init_data)
        state = await core.legacy._require_consent(identity)
        user_key = core.store.user_key(identity)
        existing = await jobs.require_job(job_id, user_key=user_key)
        order = await document_store.get_document_order(existing.payment_order_id, user_key=user_key)
        if order is None:
            raise HTTPException(status_code=404, detail="Платёжный запрос не найден")

        # `consumed` is valid for the SAME durable job. The payment is consumed
        # before publication to prevent unpaid visibility; if persistence fails
        # afterwards, retrying that same job must not demand another payment.
        if order.status not in {"approved", "consumed"}:
            raise HTTPException(
                status_code=409,
                detail="Эта оплата недоступна для повторной подготовки. Повторно не платите; обратитесь в поддержку.",
            )

        case = (state.get("cases") or {}).get(existing.case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="Дело для документа не найдено")
        current_scope = v5.v4._document_scope(case, order.document_type, order.language)
        if current_scope != order.case_fingerprint:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Материалы дела изменились после оплаты. Повторно не платите; "
                    "восстановите оплаченный состав материалов или обратитесь в поддержку."
                ),
            )

        async with payment_operation_lock(
            document_store._require_pool(),
            "miniapp-generation-retry-hardened",
            existing.id,
        ):
            job = await jobs.reset_failed_job(existing.id)
            # start_paid_generation reuses the unique payment_order_id job and
            # schedules only when it is queued. No second legal worker is born.
            scheduled = await autostart_runtime.start_paid_generation(order.id)
            if scheduled is not None:
                job = scheduled

        return {
            "payment_required": False,
            "generation_started": job.status in {"queued", "running"},
            "job": jobs.public_job(job),
        }

    _INSTALLED = True
    LOGGER.info("Installed hardened Tole payment state machine")


install_payment_hardening_runtime()
