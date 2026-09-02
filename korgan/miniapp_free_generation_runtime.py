from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Any

import asyncpg
from fastapi import Header, HTTPException

from korgan import miniapp_generation_api as generation_api
from korgan import miniapp_generation_jobs as paid_jobs
from korgan.asgi_lifespan import add_lifespan

LOGGER = logging.getLogger(__name__)
app = generation_api.app
core = generation_api.core
settings = generation_api.settings

# Keep immutable references to the paid handlers before free mode replaces the
# public route objects. Runtime dispatch below means import order can never turn
# a paid request into a free-job request (or the reverse) in a long-lived
# process/test composition.
_PAID_GENERATE = generation_api.generate_document_job
_PAID_STATUS = generation_api.generation_status
_PAID_CASE_STATUS = generation_api.case_generation_status
_PAID_RETRY = generation_api.retry_generation
_PAID_REQUIRE_JOB = paid_jobs.require_job


def _paid_scheduler_before_free():
    current = generation_api._schedule_job
    if (
        getattr(current, "__module__", "") == "korgan.miniapp_case_activity"
        and getattr(current, "__name__", "") == "_schedule_job_with_activity"
    ):
        from korgan import miniapp_case_activity as activity

        return activity._ORIGINAL_SCHEDULE_JOB
    return current


_PAID_SCHEDULE_JOB = _paid_scheduler_before_free()

_POOL: asyncpg.Pool | None = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS korgan_miniapp_free_generation_jobs (
    id UUID PRIMARY KEY,
    user_key TEXT NOT NULL,
    case_id TEXT NOT NULL,
    case_fingerprint TEXT NOT NULL,
    document_type TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'ru',
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    stage TEXT NOT NULL DEFAULT 'queued',
    progress INTEGER NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
    error_detail TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_key, case_id, case_fingerprint)
);

CREATE INDEX IF NOT EXISTS korgan_miniapp_free_generation_jobs_case_idx
ON korgan_miniapp_free_generation_jobs(user_key, case_id, created_at DESC);
"""

_INTERRUPTED = (
    "Сервис перезапустился во время подготовки документа. "
    "Запустите повтор — новая оплата не требуется."
)


@dataclass(frozen=True)
class FreeGenerationJob:
    id: str
    user_key: str
    case_id: str
    case_fingerprint: str
    document_type: str
    language: str
    status: str
    stage: str
    progress: int
    error_detail: str


def _require_pool() -> asyncpg.Pool:
    if _POOL is None:
        raise RuntimeError("Free Mini App generation job store is not initialized")
    return _POOL


def _from_row(row: Any) -> FreeGenerationJob:
    return FreeGenerationJob(
        id=str(row["id"]),
        user_key=str(row["user_key"]),
        case_id=str(row["case_id"]),
        case_fingerprint=str(row["case_fingerprint"]),
        document_type=str(row["document_type"]),
        language=str(row["language"] or "ru"),
        status=str(row["status"]),
        stage=str(row["stage"]),
        progress=int(row["progress"]),
        error_detail=str(row["error_detail"] or ""),
    )


def _public_job(job: FreeGenerationJob) -> dict[str, Any]:
    return {
        "job_id": job.id,
        "case_id": job.case_id,
        "status": job.status,
        "stage": job.stage,
        "progress": job.progress,
        "document_ready": job.status == "succeeded",
        "retryable": job.status == "failed",
        "error": job.error_detail if job.status == "failed" else "",
    }


async def _startup() -> None:
    global _POOL
    if settings.payments_enabled:
        return
    dsn = str(settings.database_url or "").strip()
    if not dsn:
        raise RuntimeError("DATABASE_URL is required for durable Mini App generation")
    if _POOL is not None:
        return
    _POOL = await asyncpg.create_pool(
        dsn=dsn,
        min_size=1,
        max_size=4,
        command_timeout=30,
    )
    async with _POOL.acquire() as connection:
        await connection.execute(_SCHEMA)
        await connection.execute(
            """
            UPDATE korgan_miniapp_free_generation_jobs
            SET status='failed', stage='interrupted', progress=0,
                error_detail=$1, finished_at=NOW(), updated_at=NOW()
            WHERE status IN ('queued', 'running')
            """,
            _INTERRUPTED,
        )


async def _shutdown() -> None:
    global _POOL
    if settings.payments_enabled:
        return
    tasks = list(generation_api._TASKS.values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    generation_api._TASKS.clear()
    pool, _POOL = _POOL, None
    if pool is not None:
        await pool.close()


async def _create_or_get_job(
    *,
    user_key: str,
    case_id: str,
    case_fingerprint: str,
    document_type: str,
    language: str,
) -> FreeGenerationJob:
    row = await _require_pool().fetchrow(
        """
        INSERT INTO korgan_miniapp_free_generation_jobs(
            id, user_key, case_id, case_fingerprint, document_type, language
        ) VALUES($1::uuid,$2,$3,$4,$5,$6)
        ON CONFLICT (user_key, case_id, case_fingerprint) DO UPDATE
        SET updated_at=korgan_miniapp_free_generation_jobs.updated_at
        RETURNING id, user_key, case_id, case_fingerprint, document_type, language,
                  status, stage, progress, error_detail
        """,
        str(uuid.uuid4()),
        user_key,
        case_id,
        case_fingerprint,
        document_type,
        language,
    )
    assert row is not None
    return _from_row(row)


async def _require_free_job(job_id: str, *, user_key: str) -> FreeGenerationJob:
    row = await _require_pool().fetchrow(
        """
        SELECT id, user_key, case_id, case_fingerprint, document_type, language,
               status, stage, progress, error_detail
        FROM korgan_miniapp_free_generation_jobs
        WHERE id=$1::uuid AND user_key=$2
        """,
        job_id,
        user_key,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Задача подготовки документа не найдена")
    return _from_row(row)


async def _require_job_dispatch(job_id: str, *, user_key: str):
    if settings.payments_enabled:
        return await _PAID_REQUIRE_JOB(job_id, user_key=user_key)
    return await _require_free_job(job_id, user_key=user_key)


async def _latest_for_case(*, user_key: str, case_id: str) -> FreeGenerationJob | None:
    row = await _require_pool().fetchrow(
        """
        SELECT id, user_key, case_id, case_fingerprint, document_type, language,
               status, stage, progress, error_detail
        FROM korgan_miniapp_free_generation_jobs
        WHERE user_key=$1 AND case_id=$2
        ORDER BY created_at DESC
        LIMIT 1
        """,
        user_key,
        case_id,
    )
    return None if row is None else _from_row(row)


async def _update_job(
    job_id: str,
    *,
    status: str,
    stage: str,
    progress: int,
    error_detail: str = "",
) -> None:
    await _require_pool().execute(
        """
        UPDATE korgan_miniapp_free_generation_jobs
        SET status=$2, stage=$3, progress=$4, error_detail=$5,
            started_at=CASE WHEN $2='running' AND started_at IS NULL THEN NOW() ELSE started_at END,
            finished_at=CASE WHEN $2 IN ('succeeded','failed') THEN NOW() ELSE NULL END,
            updated_at=NOW()
        WHERE id=$1::uuid
        """,
        job_id,
        status,
        stage,
        max(0, min(int(progress), 100)),
        str(error_detail or "")[:1000],
    )


async def _claim_job(job_id: str) -> FreeGenerationJob | None:
    row = await _require_pool().fetchrow(
        """
        UPDATE korgan_miniapp_free_generation_jobs
        SET status='running', stage='starting', progress=5,
            started_at=COALESCE(started_at, NOW()), updated_at=NOW()
        WHERE id=$1::uuid AND status='queued'
        RETURNING id, user_key, case_id, case_fingerprint, document_type, language,
                  status, stage, progress, error_detail
        """,
        job_id,
    )
    return None if row is None else _from_row(row)


async def _run_free_job(
    job: FreeGenerationJob,
    *,
    identity: str,
    document_type: str,
    context: str,
    language: str,
) -> None:
    claimed = await _claim_job(job.id)
    if claimed is None:
        LOGGER.info("Free Mini App generation job already claimed job_id=%s", job.id)
        return

    async def on_stage(stage: str, progress: int) -> None:
        await _update_job(
            job.id,
            status="running",
            stage=stage,
            progress=progress,
        )

    try:
        result = await paid_jobs._generate_payload(
            document_type,
            context,
            language,
            case_id=job.case_id,
            on_stage=on_stage,
        )
        state = await core.store.load(identity)
        case = (state.get("cases") or {}).get(job.case_id)
        if case is None:
            raise paid_jobs.GenerationFailure("Дело удалено во время подготовки документа")
        case.update(result)
        await core.store.save(identity, state)
        await _update_job(
            job.id,
            status="succeeded",
            stage="completed",
            progress=100,
        )
    except Exception as exc:
        await _update_job(
            job.id,
            status="failed",
            stage="failed",
            progress=0,
            error_detail=paid_jobs._client_detail(exc),
        )
        LOGGER.exception("Free Mini App generation job failed job_id=%s", job.id)
        raise


async def _schedule_free_job(
    *,
    job: FreeGenerationJob,
    identity: str,
    document_type: str,
    context: str,
    language: str,
) -> None:
    existing = generation_api._TASKS.get(job.id)
    if existing is not None and not existing.done():
        return
    task = asyncio.create_task(
        _run_free_job(
            job,
            identity=identity,
            document_type=document_type,
            context=context,
            language=language,
        ),
        name=f"korgan-free-generation-{job.id}",
    )
    generation_api._TASKS[job.id] = task

    def finished(done: asyncio.Task[None]) -> None:
        generation_api._consume_task_result(done)
        if generation_api._TASKS.get(job.id) is done:
            generation_api._TASKS.pop(job.id, None)

    task.add_done_callback(finished)


async def _schedule_job_dispatch(
    *,
    job: Any,
    identity: str,
    document_type: str,
    context: str,
    language: str,
) -> None:
    scheduler = _PAID_SCHEDULE_JOB if settings.payments_enabled else _schedule_free_job
    await scheduler(
        job=job,
        identity=identity,
        document_type=document_type,
        context=context,
        language=language,
    )


async def _reset_failed(job_id: str, *, user_key: str) -> FreeGenerationJob:
    row = await _require_pool().fetchrow(
        """
        UPDATE korgan_miniapp_free_generation_jobs
        SET status='queued', stage='queued', progress=0, error_detail='',
            started_at=NULL, finished_at=NULL, updated_at=NOW()
        WHERE id=$1::uuid AND user_key=$2 AND status='failed'
        RETURNING id, user_key, case_id, case_fingerprint, document_type, language,
                  status, stage, progress, error_detail
        """,
        job_id,
        user_key,
    )
    if row is None:
        raise HTTPException(status_code=409, detail="Эту задачу нельзя запустить повторно")
    return _from_row(row)


def _install_free_scheduler() -> None:
    """Install runtime dispatch without dropping an existing activity wrapper."""
    current = generation_api._schedule_job
    if (
        getattr(current, "__module__", "") == "korgan.miniapp_case_activity"
        and getattr(current, "__name__", "") == "_schedule_job_with_activity"
    ):
        from korgan import miniapp_case_activity as activity

        activity._ORIGINAL_SCHEDULE_JOB = _schedule_job_dispatch
        generation_api._schedule_job = activity._schedule_job_with_activity
        return
    generation_api._schedule_job = _schedule_job_dispatch


if not settings.payments_enabled:
    add_lifespan(app, startup=_startup, shutdown=_shutdown)

    # One route surface serves both modes. The import-time mode decides whether
    # free durability infrastructure is installed, but every request re-checks
    # the current mode before touching a free or paid store. This makes the
    # composition safe when settings are monkeypatched by integration tests and
    # avoids import-order state leaks in long-lived ASGI processes.
    generation_api._drop("/miniapp/documents/generate", "POST")
    generation_api._drop("/miniapp/documents/generation/{job_id}", "GET")
    generation_api._drop("/miniapp/cases/{case_id}/generation", "GET")
    generation_api._drop("/miniapp/documents/generation/{job_id}/retry", "POST")

    @app.post("/miniapp/documents/generate")
    async def generate_free_document_job(
        payload: core.GenerateRequest,
        x_telegram_init_data: str = Header(default=""),
    ) -> dict[str, Any]:
        if settings.payments_enabled:
            return await _PAID_GENERATE(payload, x_telegram_init_data=x_telegram_init_data)
        identity, state, case, user_key, scope, document_type, language = (
            await generation_api._generation_scope(payload, x_telegram_init_data)
        )
        job = await _create_or_get_job(
            user_key=user_key,
            case_id=payload.case_id,
            case_fingerprint=scope,
            document_type=document_type,
            language=language,
        )
        if job.status == "succeeded":
            return {
                "payment_required": False,
                "generation_started": False,
                "job": _public_job(job),
                "document": generation_api._ready_document(state, payload.case_id),
            }
        if job.status == "queued":
            await _schedule_job_dispatch(
                job=job,
                identity=identity,
                document_type=document_type,
                context=core._case_context(case),
                language=language,
            )
        return {
            "payment_required": False,
            "generation_started": job.status in {"queued", "running"},
            "job": _public_job(job),
        }

    @app.get("/miniapp/documents/generation/{job_id}")
    async def free_generation_status(
        job_id: str,
        x_telegram_init_data: str = Header(default=""),
    ) -> dict[str, Any]:
        if settings.payments_enabled:
            return await _PAID_STATUS(job_id, x_telegram_init_data=x_telegram_init_data)
        identity = core.legacy._identity(x_telegram_init_data)
        state = await core.legacy._require_consent(identity)
        user_key = core.store.user_key(identity)
        job = await _require_free_job(job_id, user_key=user_key)
        result: dict[str, Any] = {"job": _public_job(job)}
        if job.status == "succeeded":
            result["document"] = generation_api._ready_document(state, job.case_id)
        return result

    @app.get("/miniapp/cases/{case_id}/generation")
    async def free_case_generation_status(
        case_id: str,
        x_telegram_init_data: str = Header(default=""),
    ) -> dict[str, Any]:
        if settings.payments_enabled:
            return await _PAID_CASE_STATUS(case_id, x_telegram_init_data=x_telegram_init_data)
        identity = core.legacy._identity(x_telegram_init_data)
        state = await core.legacy._require_consent(identity)
        if case_id not in (state.get("cases") or {}):
            raise HTTPException(status_code=404, detail="Case not found")
        user_key = core.store.user_key(identity)
        job = await _latest_for_case(user_key=user_key, case_id=case_id)
        if job is None:
            return {"job": None}
        result: dict[str, Any] = {"job": _public_job(job)}
        if job.status == "succeeded":
            result["document"] = generation_api._ready_document(state, case_id)
        return result

    @app.post("/miniapp/documents/generation/{job_id}/retry")
    async def retry_free_generation(
        job_id: str,
        x_telegram_init_data: str = Header(default=""),
    ) -> dict[str, Any]:
        if settings.payments_enabled:
            return await _PAID_RETRY(job_id, x_telegram_init_data=x_telegram_init_data)
        identity = core.legacy._identity(x_telegram_init_data)
        state = await core.legacy._require_consent(identity)
        user_key = core.store.user_key(identity)
        existing = await _require_free_job(job_id, user_key=user_key)
        case = (state.get("cases") or {}).get(existing.case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="Дело для документа не найдено")
        current_scope = generation_api.v5.v4._document_scope(
            case,
            existing.document_type,
            existing.language,
        )
        if current_scope != existing.case_fingerprint:
            raise HTTPException(
                status_code=409,
                detail="Материалы дела изменились. Запустите подготовку как новую задачу.",
            )
        job = await _reset_failed(job_id, user_key=user_key)
        await _schedule_job_dispatch(
            job=job,
            identity=identity,
            document_type=job.document_type,
            context=core._case_context(case),
            language=job.language,
        )
        return {
            "payment_required": False,
            "generation_started": True,
            "job": _public_job(job),
        }

    # Case activity may already be imported by another ASGI/test composition.
    # Keep it outermost and swap only its scheduler delegate. Both scheduler and
    # job lookup dispatch dynamically so paid mode never touches the free DB.
    _install_free_scheduler()
    paid_jobs.require_job = _require_job_dispatch
