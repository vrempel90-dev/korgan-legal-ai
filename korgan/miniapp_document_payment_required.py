from __future__ import annotations

from typing import NoReturn

from fastapi import Header, HTTPException

from korgan import miniapp_generation_api as generation_api

app = generation_api.app
settings = generation_api.settings

_PAYMENT_REQUIRED_DETAIL = (
    "Подготовка документов доступна только после подтвержденной оплаты. "
    "Платежный контур временно не настроен, поэтому генерация не запущена."
)


def require_document_payments_enabled(payments_enabled: bool) -> None:
    """Fail closed when the paid-document runtime is unavailable.

    A document is a paid product in KORGAN. Disabling payment infrastructure
    must never silently turn document generation into a free path. Development,
    staging and production therefore share the same invariant: no confirmed
    payment runtime -> no legal research, no LLM drafting and no DOCX job.
    """
    if not payments_enabled:
        raise HTTPException(status_code=503, detail=_PAYMENT_REQUIRED_DETAIL)


def _blocked() -> NoReturn:
    require_document_payments_enabled(False)
    raise AssertionError("unreachable")


def install_paid_document_fail_closed() -> None:
    """Replace every free-generation entry point when payments are disabled."""
    if settings.payments_enabled:
        return

    generation_api._drop("/miniapp/documents/generate", "POST")
    generation_api._drop("/miniapp/documents/generation/{job_id}/retry", "POST")
    generation_api._drop("/miniapp/documents/payments/{order_id}/retry", "POST")

    @app.post("/miniapp/documents/generate")
    async def blocked_document_generation(
        x_telegram_init_data: str = Header(default=""),
    ) -> dict[str, object]:
        del x_telegram_init_data
        _blocked()

    @app.post("/miniapp/documents/generation/{job_id}/retry")
    async def blocked_document_generation_retry(
        job_id: str,
        x_telegram_init_data: str = Header(default=""),
    ) -> dict[str, object]:
        del job_id, x_telegram_init_data
        _blocked()

    @app.post("/miniapp/documents/payments/{order_id}/retry")
    async def blocked_paid_document_retry(
        order_id: int,
        x_telegram_init_data: str = Header(default=""),
    ) -> dict[str, object]:
        del order_id, x_telegram_init_data
        _blocked()


install_paid_document_fail_closed()
