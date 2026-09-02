"""Серверная история дела и одноразовое уведомление о готовом документе.

Модуль не меняет KORGAN UI и не вмешивается в юридическое ядро или оплату.
Он подключается поверх уже существующего persisted generation runtime:

* пишет понятные пользователю события дела в PostgreSQL;
* не дублирует одно и то же событие одного generation job;
* после фактического ``succeeded`` отправляет короткое Telegram-уведомление;
* предоставляет историю конкретного дела для экрана «Мои дела».

Источник истины остаётся прежним: статус generation job и сохранённый документ.
Уведомление никогда не переводит дело в READY само по себе.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Any

import asyncpg
import httpx
from fastapi import Header, HTTPException

from korgan import miniapp_generation_api as generation_api
from korgan import miniapp_generation_jobs as jobs
from korgan.asgi_lifespan import add_lifespan
from korgan.config import get_settings

LOGGER = logging.getLogger(__name__)
app = generation_api.app
core = generation_api.core
settings = generation_api.settings

_POOL: asyncpg.Pool | None = None
_ORIGINAL_SCHEDULE_JOB = generation_api._schedule_job
_TELEGRAM_API = "https://api.telegram.org"
_NOTIFY_TIMEOUT = 15.0

_SCHEMA = """
CREATE TABLE IF NOT EXISTS korgan_miniapp_case_activity (
    id BIGSERIAL PRIMARY KEY,
    user_key TEXT NOT NULL,
    case_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
    detail TEXT NOT NULL DEFAULT '',
    notification_status TEXT NOT NULL DEFAULT 'not_applicable'
        CHECK (notification_status IN ('not_applicable', 'pending', 'sent', 'failed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_key, case_id, job_id, event_type)
);

CREATE INDEX IF NOT EXISTS korgan_miniapp_case_activity_case_idx
ON korgan_miniapp_case_activity(user_key, case_id, created_at DESC);
"""

_LABELS_RU = {
    "queued": "Документ поставлен в очередь",
    "ready": "Документ готов",
    "failed": "Подготовка документа не завершилась",
}

_LABELS_KK = {
    "queued": "Құжат кезекке қойылды",
    "ready": "Құжат дайын",
    "failed": "Құжат дайындау аяқталмады",
}


@dataclass(frozen=True)
class CaseActivity:
    id: int
    case_id: str
    job_id: str
    event_type: str
    progress: int
    detail: str
    notification_status: str
    created_at: Any


def _require_pool() -> asyncpg.Pool:
    if _POOL is None:
        raise RuntimeError("Mini App case activity store is not initialized")
    return _POOL


async def init_case_activity_store(database_url: str, *, enabled: bool) -> None:
    global _POOL
    if not enabled:
        return
    if not str(database_url or "").strip():
        raise RuntimeError("PAYMENTS_ENABLED requires DATABASE_URL for case activity")
    if _POOL is not None:
        return
    _POOL = await asyncpg.create_pool(
        dsn=database_url,
        min_size=1,
        max_size=3,
        command_timeout=30,
    )
    async with _POOL.acquire() as connection:
        await connection.execute(_SCHEMA)


async def close_case_activity_store() -> None:
    global _POOL
    if _POOL is not None:
        await _POOL.close()
        _POOL = None


async def _startup() -> None:
    await init_case_activity_store(settings.database_url, enabled=settings.payments_enabled)


async def _shutdown() -> None:
    await close_case_activity_store()


add_lifespan(app, startup=_startup, shutdown=_shutdown)


def _label(event_type: str, language: str) -> str:
    labels = _LABELS_KK if language == "kk" else _LABELS_RU
    return labels.get(event_type, event_type)


async def record_case_activity(
    *,
    user_key: str,
    case_id: str,
    job_id: str,
    event_type: str,
    progress: int,
    detail: str,
    notification_status: str = "not_applicable",
) -> bool:
    """Записать событие один раз; ``True`` только для новой строки."""
    if not settings.payments_enabled:
        return False
    row = await _require_pool().fetchrow(
        """
        INSERT INTO korgan_miniapp_case_activity(
            user_key, case_id, job_id, event_type, progress, detail, notification_status
        ) VALUES($1,$2,$3,$4,$5,$6,$7)
        ON CONFLICT (user_key, case_id, job_id, event_type) DO NOTHING
        RETURNING id
        """,
        user_key,
        case_id,
        job_id,
        event_type,
        max(0, min(int(progress), 100)),
        str(detail or "")[:500],
        notification_status,
    )
    return row is not None


async def _set_notification_status(
    *,
    user_key: str,
    case_id: str,
    job_id: str,
    status: str,
) -> None:
    if not settings.payments_enabled:
        return
    await _require_pool().execute(
        """
        UPDATE korgan_miniapp_case_activity
        SET notification_status=$4, updated_at=NOW()
        WHERE user_key=$1 AND case_id=$2 AND job_id=$3 AND event_type='ready'
        """,
        user_key,
        case_id,
        job_id,
        status,
    )


def _notification_payload(identity: str, case: dict[str, Any]) -> dict[str, Any]:
    language = "kk" if str(case.get("language") or "") == "kk" else "ru"
    title = str(case.get("title") or case.get("filename") or "").strip()
    if language == "kk":
        text = "KORGAN: құжатыңыз дайын. «Менің істерім» бөлімінен ашуға болады."
    else:
        text = "KORGAN: ваш документ готов. Откройте его в разделе «Мои дела»."
    if title:
        text = f"{text}\n\n{title[:160]}"

    payload: dict[str, Any] = {"chat_id": identity, "text": text}
    public_url = os.getenv("MINIAPP_PUBLIC_URL", "").strip()
    if public_url.startswith("https://"):
        button = "KORGAN-ды ашу" if language == "kk" else "Открыть KORGAN"
        payload["reply_markup"] = {
            "inline_keyboard": [[{"text": button, "web_app": {"url": public_url}}]],
        }
    return payload


async def _send_ready_notification(identity: str, case: dict[str, Any]) -> bool:
    token = (get_settings().telegram_bot_token or "").strip()
    if not token:
        LOGGER.warning("KORGAN ready notification skipped: TELEGRAM_BOT_TOKEN is empty")
        return False

    try:
        async with httpx.AsyncClient(timeout=_NOTIFY_TIMEOUT) as client:
            response = await client.post(
                f"{_TELEGRAM_API}/bot{token}/sendMessage",
                json=_notification_payload(identity, case),
            )
    except httpx.HTTPError:
        LOGGER.exception("KORGAN ready notification network failure")
        return False

    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.is_success and body.get("ok"):
        return True

    LOGGER.warning(
        "KORGAN ready notification rejected status=%s description=%s",
        response.status_code,
        str(body.get("description") or "unknown")[:200],
    )
    return False


async def _capture_terminal(job: jobs.GenerationJob, *, identity: str) -> None:
    """После завершения task зафиксировать только фактический persisted state."""
    try:
        latest = await jobs.require_job(job.id, user_key=job.user_key)
    except Exception:
        LOGGER.exception("KORGAN activity could not reload generation job id=%s", job.id)
        return

    if latest.status not in {"succeeded", "failed"}:
        return

    event_type = "ready" if latest.status == "succeeded" else "failed"
    progress = 100 if latest.status == "succeeded" else latest.progress
    detail = ""
    case: dict[str, Any] = {}
    if latest.status == "succeeded":
        try:
            state = await core.store.load(identity)
            case = (state.get("cases") or {}).get(latest.case_id) or {}
        except Exception:
            LOGGER.exception("KORGAN activity could not reload case id=%s", latest.case_id)
        # READY в истории разрешён только вместе с реально сохранённым файлом.
        if not case.get("document_base64") or not str(case.get("filename") or "").strip():
            return
        detail = str(case.get("filename") or "")
    else:
        detail = latest.error_detail

    is_new = await record_case_activity(
        user_key=latest.user_key,
        case_id=latest.case_id,
        job_id=latest.id,
        event_type=event_type,
        progress=progress,
        detail=detail,
        notification_status="pending" if event_type == "ready" else "not_applicable",
    )
    if not is_new or event_type != "ready":
        return

    sent = await _send_ready_notification(identity, case)
    await _set_notification_status(
        user_key=latest.user_key,
        case_id=latest.case_id,
        job_id=latest.id,
        status="sent" if sent else "failed",
    )


async def _schedule_job_with_activity(
    *,
    job: jobs.GenerationJob,
    identity: str,
    document_type: str,
    context: str,
    language: str,
) -> None:
    """Добавить аудит и terminal notification, не меняя scheduler semantics."""
    await record_case_activity(
        user_key=job.user_key,
        case_id=job.case_id,
        job_id=job.id,
        event_type="queued",
        progress=max(job.progress, 0),
        detail=_label("queued", language),
    )

    before = generation_api._TASKS.get(job.id)
    await _ORIGINAL_SCHEDULE_JOB(
        job=job,
        identity=identity,
        document_type=document_type,
        context=context,
        language=language,
    )
    task = generation_api._TASKS.get(job.id)
    if task is None or task is before:
        return

    def completed(_: asyncio.Task[None]) -> None:
        asyncio.create_task(
            _capture_terminal(job, identity=identity),
            name=f"korgan-case-activity-{job.id}",
        )

    task.add_done_callback(completed)


# Один внешний wrapper: не трогаем generation engine, legal pipeline и payment gate.
generation_api._schedule_job = _schedule_job_with_activity


@app.get("/miniapp/cases/{case_id}/activity")
async def case_activity(
    case_id: str,
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    identity = core.legacy._identity(x_telegram_init_data)
    state = await core.legacy._require_consent(identity)
    case = (state.get("cases") or {}).get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    if not settings.payments_enabled:
        return {"case_id": case_id, "events": []}

    user_key = core.store.user_key(identity)
    rows = await _require_pool().fetch(
        """
        SELECT id, case_id, job_id, event_type, progress, detail,
               notification_status, created_at
        FROM korgan_miniapp_case_activity
        WHERE user_key=$1 AND case_id=$2
        ORDER BY created_at ASC, id ASC
        LIMIT 100
        """,
        user_key,
        case_id,
    )
    language = "kk" if str(case.get("language") or "") == "kk" else "ru"
    events = [
        {
            "id": int(row["id"]),
            "case_id": str(row["case_id"]),
            "job_id": str(row["job_id"]),
            "type": str(row["event_type"]),
            "label": _label(str(row["event_type"]), language),
            "progress": int(row["progress"]),
            "detail": str(row["detail"] or ""),
            "notification_status": str(row["notification_status"]),
            "created_at": row["created_at"].isoformat(),
        }
        for row in rows
    ]
    return {"case_id": case_id, "events": events}
