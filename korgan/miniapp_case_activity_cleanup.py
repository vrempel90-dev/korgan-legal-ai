"""Privacy cleanup bridge for Mini App case activity.

The activity ledger is deliberately auxiliary to generation, but deletion is not
best-effort: once the API reports that a case or the user's Mini App data was
deleted, the independent activity rows must be gone as well. This module is
loaded by the recovery ASGI composition after ``miniapp_case_activity`` and:

* purges persisted activity on DELETE /miniapp/cases/{case_id};
* purges all persisted activity on DELETE /miniapp/me;
* tombstones deleted case ids in-process so an already-running generation task
  cannot write a terminal event after deletion;
* uses the main state-store pool as a fallback if the auxiliary activity pool is
  unavailable, so privacy cleanup does not depend on the audit pool health.

No UI, payment, legal or generation semantics are changed.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

import asyncpg
from fastapi import Request
from fastapi.responses import JSONResponse, Response

from korgan import miniapp_api_v2 as core
from korgan import miniapp_case_activity as activity

LOGGER = logging.getLogger(__name__)

_DELETED_CASES: set[tuple[str, str]] = set()
_ORIGINAL_RECORD_CASE_ACTIVITY = activity.record_case_activity


def _activity_pool() -> asyncpg.Pool | None:
    """Prefer the ledger pool, but privacy cleanup may use the canonical DB pool."""
    return activity._POOL or core.store.pool


async def _delete_case_rows(*, user_key: str, case_id: str) -> None:
    pool = _activity_pool()
    if pool is None:
        return
    try:
        await pool.execute(
            "DELETE FROM korgan_miniapp_case_activity WHERE user_key=$1 AND case_id=$2",
            user_key,
            case_id,
        )
    except asyncpg.UndefinedTableError:
        # A deployment where the auxiliary schema was never created has no
        # activity rows to retain, therefore deletion is already complete.
        return


async def _delete_user_rows(*, user_key: str) -> None:
    pool = _activity_pool()
    if pool is None:
        return
    try:
        await pool.execute(
            "DELETE FROM korgan_miniapp_case_activity WHERE user_key=$1",
            user_key,
        )
    except asyncpg.UndefinedTableError:
        return


async def _guarded_record_case_activity(**kwargs: Any) -> bool:
    key = (str(kwargs.get("user_key") or ""), str(kwargs.get("case_id") or ""))
    if key in _DELETED_CASES:
        return False
    return await _ORIGINAL_RECORD_CASE_ACTIVITY(**kwargs)


# Both scheduler and terminal capture resolve this module global at call time,
# so replacing the function once is enough to protect already-running jobs.
activity.record_case_activity = _guarded_record_case_activity


async def _identity_and_cases(request: Request) -> tuple[str, str, set[str]] | None:
    """Resolve deletion target without making the normal endpoint depend on us."""
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    try:
        identity = core.legacy._identity(init_data)
    except Exception:
        return None
    user_key = core.store.user_key(identity)

    path = request.url.path
    if path == "/miniapp/me":
        case_ids: set[str] = set()
        try:
            state = await core.legacy._state(identity)
            case_ids = {str(case_id) for case_id in (state.get("cases") or {})}
        except Exception:
            LOGGER.exception("KORGAN could not snapshot case ids before user-data deletion")
        return identity, user_key, case_ids

    prefix = "/miniapp/cases/"
    if path.startswith(prefix):
        case_id = path[len(prefix) :].strip("/")
        if case_id and "/" not in case_id:
            return identity, user_key, {case_id}
    return None


@activity.app.middleware("http")
async def purge_activity_on_delete(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    if request.method != "DELETE":
        return await call_next(request)

    target = await _identity_and_cases(request)
    if target is None:
        return await call_next(request)

    _identity, user_key, case_ids = target
    tombstones = {(user_key, case_id) for case_id in case_ids}
    _DELETED_CASES.update(tombstones)

    response = await call_next(request)
    if response.status_code >= 400:
        _DELETED_CASES.difference_update(tombstones)
        return response

    try:
        if request.url.path == "/miniapp/me":
            await _delete_user_rows(user_key=user_key)
        else:
            for case_id in case_ids:
                await _delete_case_rows(user_key=user_key, case_id=case_id)
    except Exception:
        # Do not return a false "deleted" success while auxiliary personal data
        # may still exist. The canonical state has already been deleted, so a
        # retry is safe and will retry this ledger cleanup.
        LOGGER.exception("KORGAN activity privacy cleanup failed path=%s", request.url.path)
        return JSONResponse(
            status_code=503,
            content={
                "detail": "Основные данные удалены, но очистка истории дела не завершена. Повторите удаление."
            },
        )

    return response
