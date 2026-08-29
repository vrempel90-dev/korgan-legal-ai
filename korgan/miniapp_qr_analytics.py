from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from korgan import miniapp_api as core

router = APIRouter()

_ALLOWED_EVENTS = {
    "qr_open",
    "ai_lawyer_open",
    "document_start",
    "payment_confirmed",
}
_SOURCE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
_schema_lock = asyncio.Lock()
_schema_ready = False


class AcquisitionEvent(BaseModel):
    event: str = Field(min_length=1, max_length=64)
    source: str = Field(default="qr", min_length=1, max_length=32)


def _retention_days() -> int:
    try:
        value = int(os.getenv("MINIAPP_RETENTION_DAYS", "30"))
    except ValueError:
        value = 30
    return max(1, min(value, 365))


def _normalize_source(value: str) -> str:
    source = str(value or "").strip().lower()
    if not _SOURCE_RE.fullmatch(source):
        raise HTTPException(status_code=422, detail="Invalid acquisition source")
    return source


def _admin_ids() -> set[str]:
    raw = os.getenv("ADMIN_TELEGRAM_IDS", "")
    return {part for part in re.split(r"[\s,;]+", raw.strip()) if part}


def _require_admin(init_data: str) -> str:
    user_id = core._identity(init_data)
    if user_id not in _admin_ids():
        raise HTTPException(status_code=403, detail="Admin access required")
    return user_id


def _pool():
    pool = core.store.pool
    if pool is None:
        raise HTTPException(status_code=503, detail="Analytics storage is not ready")
    return pool


async def _ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    async with _schema_lock:
        if _schema_ready:
            return
        pool = _pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS korgan_miniapp_acquisition_events (
                    id BIGSERIAL PRIMARY KEY,
                    user_key TEXT NOT NULL,
                    source TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_korgan_acquisition_source_time "
                "ON korgan_miniapp_acquisition_events(source, created_at)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_korgan_acquisition_funnel "
                "ON korgan_miniapp_acquisition_events(source, event_type, created_at)"
            )
        _schema_ready = True


async def _purge_expired() -> None:
    pool = _pool()
    await pool.execute(
        "DELETE FROM korgan_miniapp_acquisition_events "
        "WHERE created_at < NOW() - ($1 * INTERVAL '1 day')",
        _retention_days(),
    )


@router.post("/miniapp/analytics/event")
async def record_acquisition_event(
    payload: AcquisitionEvent,
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    if payload.event not in _ALLOWED_EVENTS:
        raise HTTPException(status_code=422, detail="Unsupported analytics event")
    source = _normalize_source(payload.source)
    user_id = core._identity(x_telegram_init_data)
    user_key = core.store.user_key(user_id)

    await _ensure_schema()
    pool = _pool()
    await pool.execute(
        "INSERT INTO korgan_miniapp_acquisition_events(user_key, source, event_type) "
        "VALUES($1, $2, $3)",
        user_key,
        source,
        payload.event,
    )
    await _purge_expired()
    return {"ok": True, "source": source, "event": payload.event}


@router.get("/miniapp/admin/analytics/acquisition")
async def acquisition_summary(
    source: str = Query(default="qr", min_length=1, max_length=32),
    days: int = Query(default=30, ge=1, le=365),
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    _require_admin(x_telegram_init_data)
    source = _normalize_source(source)
    await _ensure_schema()

    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = await _pool().fetch(
        """
        SELECT event_type,
               COUNT(*)::BIGINT AS events,
               COUNT(DISTINCT user_key)::BIGINT AS unique_users
        FROM korgan_miniapp_acquisition_events
        WHERE source=$1 AND created_at >= $2
        GROUP BY event_type
        """,
        source,
        since,
    )

    funnel: dict[str, dict[str, int]] = {
        event: {"events": 0, "unique_users": 0} for event in sorted(_ALLOWED_EVENTS)
    }
    for row in rows:
        event_type = str(row["event_type"])
        if event_type in funnel:
            funnel[event_type] = {
                "events": int(row["events"] or 0),
                "unique_users": int(row["unique_users"] or 0),
            }

    opened = funnel["qr_open"]["unique_users"]

    def conversion(event: str) -> float:
        if opened <= 0:
            return 0.0
        return round((funnel[event]["unique_users"] / opened) * 100.0, 1)

    return {
        "ok": True,
        "source": source,
        "days": days,
        "funnel": funnel,
        "conversion_percent": {
            "ai_lawyer": conversion("ai_lawyer_open"),
            "document": conversion("document_start"),
            "payment": conversion("payment_confirmed"),
        },
    }
