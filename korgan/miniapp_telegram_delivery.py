"""Fail-closed compatibility route for retired Telegram document delivery.

KORGAN Mini App now gives Word files directly through the signed document-access
route. A stale client must never make the backend forward a private legal
document to the Telegram bot, so the old endpoint stays present only to return
an explicit retirement response.
"""

from __future__ import annotations

from typing import Any

from fastapi import Header, HTTPException

from korgan.miniapp_payment_idempotency import app


@app.post("/miniapp/cases/{case_id}/document/telegram")
async def send_document_to_telegram(
    case_id: str,
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    from korgan import miniapp_api_v2 as core

    identity = core.legacy._identity(x_telegram_init_data)
    await core.legacy._require_consent(identity)
    raise HTTPException(
        status_code=410,
        detail=(
            "Отправка документов через Telegram отключена. "
            "Скачайте текущую версию документа непосредственно в KORGAN Mini App."
        ),
    )
