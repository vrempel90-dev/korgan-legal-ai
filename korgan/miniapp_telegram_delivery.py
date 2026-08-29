"""Отправка готового документа в чат Telegram.

Зачем
-----
Мини-апп открывается во встроенном браузере Telegram, а он блокирует
обычное сохранение файла: фронтенд делает

    URL.createObjectURL(blob) → <a download> → a.click()

и в WebView это молча ничего не делает — ни файла, ни ошибки. В логах видно
ровно это: документ сгенерирован, `GET /miniapp/cases/.../document` отвечает
200 четыре раза подряд, а пользователь говорит, что скачать не может.

Надёжный способ отдать файл из мини-аппа — послать его ботом в личный чат.
Идентификатор пользователя Telegram, полученный из подписанной initData,
одновременно является chat_id личного чата.

Ограничение, о котором нужно сказать пользователю понятными словами: бот не
может написать первым. Если человек ни разу не открывал бота, Telegram
ответит 403, и в ответе будет просьба нажать «Старт» в боте.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

import httpx
from fastapi import Header, HTTPException

from korgan.config import get_settings
from korgan.miniapp_payment_idempotency import app

LOGGER = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org"
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_SEND_TIMEOUT = 60.0

# Telegram принимает документы до 50 МБ; наши .docx на порядки меньше, но
# ограничение лучше проверять до отправки, чтобы дать понятную ошибку.
_MAX_DOCUMENT_BYTES = 45 * 1024 * 1024


def _caption(case: dict[str, Any]) -> str:
    title = str(case.get("title") or "Документ KORGAN").strip()
    if str(case.get("release_status") or "") == "preliminary":
        return (
            f"{title}\n\n"
            "Это предварительный проект: перед подачей закройте отмеченные в документе вопросы."
        )
    return title


@app.post("/miniapp/cases/{case_id}/document/telegram")
async def send_document_to_telegram(
    case_id: str,
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    """Прислать готовый .docx в личный чат Telegram."""
    from korgan import miniapp_api_v2 as core

    identity = core.legacy._identity(x_telegram_init_data)
    state = await core.legacy._require_consent(identity)
    case = state.get("cases", {}).get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Дело не найдено")

    encoded = str(case.get("document_base64") or "")
    if not encoded:
        raise HTTPException(status_code=404, detail="Документ по этому делу ещё не готов")

    try:
        payload = base64.b64decode(encoded)
    except Exception as exc:  # noqa: BLE001 — испорченное хранилище, не ошибка клиента
        LOGGER.exception("KORGAN telegram delivery: не удалось раскодировать документ case_id=%s", case_id)
        raise HTTPException(status_code=500, detail="Файл документа повреждён, сгенерируйте заново") from exc

    if not payload:
        raise HTTPException(status_code=404, detail="Документ по этому делу ещё не готов")
    if len(payload) > _MAX_DOCUMENT_BYTES:
        raise HTTPException(status_code=413, detail="Документ слишком большой для отправки в Telegram")

    token = (get_settings().telegram_bot_token or "").strip()
    if not token:
        raise HTTPException(status_code=503, detail="Отправка в Telegram не настроена")

    filename = str(case.get("filename") or "KORGAN_document.docx")

    try:
        async with httpx.AsyncClient(timeout=_SEND_TIMEOUT) as client:
            response = await client.post(
                f"{_TELEGRAM_API}/bot{token}/sendDocument",
                data={"chat_id": identity, "caption": _caption(case)[:1024]},
                files={"document": (filename, payload, _DOCX_MIME)},
            )
    except httpx.HTTPError as exc:
        LOGGER.exception("KORGAN telegram delivery: сеть недоступна case_id=%s", case_id)
        raise HTTPException(status_code=502, detail="Telegram сейчас недоступен, попробуйте ещё раз") from exc

    body: dict[str, Any] = {}
    try:
        body = response.json()
    except ValueError:
        body = {}

    if not body.get("ok"):
        description = str(body.get("description") or f"HTTP {response.status_code}")
        LOGGER.error(
            "KORGAN telegram delivery FAILED case_id=%s status=%s description=%s",
            case_id,
            response.status_code,
            description,
        )
        # Бот не может написать первым — самая частая причина, и она чинится
        # одним действием пользователя.
        if response.status_code == 403 or "bot can't initiate" in description.lower():
            raise HTTPException(
                status_code=409,
                detail="Откройте бота KORGAN в Telegram и нажмите «Старт», затем повторите отправку.",
            )
        raise HTTPException(status_code=502, detail="Не удалось отправить документ в Telegram")

    LOGGER.info("KORGAN telegram delivery OK case_id=%s bytes=%d", case_id, len(payload))
    return {
        "ok": True,
        "delivered_to": "telegram",
        "filename": filename,
        "message": "Документ отправлен вам в чат с ботом KORGAN.",
    }
