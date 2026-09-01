from __future__ import annotations

import base64
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import asyncpg
from fastapi import HTTPException

from korgan import miniapp_document_payments as document_store

LOGGER = logging.getLogger(__name__)
_POOL: asyncpg.Pool | None = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS korgan_miniapp_generation_jobs (
    id UUID PRIMARY KEY,
    payment_order_id BIGINT NOT NULL UNIQUE
        REFERENCES korgan_miniapp_document_orders(id),
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
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS korgan_miniapp_generation_jobs_owner_idx
ON korgan_miniapp_generation_jobs(user_key, created_at DESC);

CREATE INDEX IF NOT EXISTS korgan_miniapp_generation_jobs_case_idx
ON korgan_miniapp_generation_jobs(user_key, case_id, created_at DESC);

CREATE INDEX IF NOT EXISTS korgan_miniapp_generation_jobs_status_idx
ON korgan_miniapp_generation_jobs(status, updated_at);
"""


@dataclass(frozen=True)
class GenerationJob:
    id: str
    payment_order_id: int
    user_key: str
    case_id: str
    status: str
    stage: str
    progress: int
    error_detail: str


def _require_pool() -> asyncpg.Pool:
    if _POOL is None:
        raise RuntimeError("Mini App generation job store is not initialized")
    return _POOL


def _from_row(row: Any) -> GenerationJob:
    return GenerationJob(
        id=str(row["id"]),
        payment_order_id=int(row["payment_order_id"]),
        user_key=str(row["user_key"]),
        case_id=str(row["case_id"]),
        status=str(row["status"]),
        stage=str(row["stage"]),
        progress=int(row["progress"]),
        error_detail=str(row["error_detail"] or ""),
    )


async def init_generation_job_store(database_url: str, *, enabled: bool) -> None:
    global _POOL
    if not enabled:
        return
    if not str(database_url or "").strip():
        raise RuntimeError("PAYMENTS_ENABLED requires DATABASE_URL for generation jobs")
    if _POOL is not None:
        return
    _POOL = await asyncpg.create_pool(
        dsn=database_url,
        min_size=1,
        max_size=4,
        command_timeout=30,
    )
    async with _POOL.acquire() as connection:
        await connection.execute(_SCHEMA)
    await recover_interrupted_jobs(_POOL)


async def close_generation_job_store() -> None:
    global _POOL
    if _POOL is not None:
        await _POOL.close()
        _POOL = None


async def recover_interrupted_jobs(pool: Any) -> None:
    await pool.execute(
        """
        UPDATE korgan_miniapp_generation_jobs
        SET status='failed', stage='interrupted', progress=0,
            error_detail='Сервис перезапустился во время подготовки документа. Запустите повтор без новой оплаты.',
            finished_at=NOW(), updated_at=NOW()
        WHERE status IN ('queued', 'running')
        """
    )


async def create_or_get_job(
    *,
    payment_order_id: int,
    user_key: str,
    case_id: str,
    case_fingerprint: str,
    document_type: str,
    language: str,
) -> GenerationJob:
    row = await _require_pool().fetchrow(
        """
        INSERT INTO korgan_miniapp_generation_jobs(
            id, payment_order_id, user_key, case_id, case_fingerprint,
            document_type, language
        ) VALUES($1::uuid,$2,$3,$4,$5,$6,$7)
        ON CONFLICT (payment_order_id) DO UPDATE
        SET updated_at=korgan_miniapp_generation_jobs.updated_at
        RETURNING id, payment_order_id, user_key, case_id,
                  status, stage, progress, error_detail
        """,
        str(uuid.uuid4()),
        payment_order_id,
        user_key,
        case_id,
        case_fingerprint,
        document_type,
        language,
    )
    assert row is not None
    job = _from_row(row)
    if job.user_key != user_key:
        raise HTTPException(status_code=404, detail="Задача подготовки документа не найдена")
    return job


async def require_job(job_id: str, *, user_key: str) -> GenerationJob:
    row = await _require_pool().fetchrow(
        """
        SELECT id, payment_order_id, user_key, case_id,
               status, stage, progress, error_detail
        FROM korgan_miniapp_generation_jobs
        WHERE id=$1 AND user_key=$2
        """,
        job_id,
        user_key,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Задача подготовки документа не найдена")
    return _from_row(row)


async def latest_job_for_case(
    *,
    user_key: str,
    case_id: str,
    case_fingerprint: str | None = None,
) -> GenerationJob | None:
    """Последняя задача подготовки документа по делу.

    Клиент теряет `job_id` при любом закрытии Mini App, поэтому дело — второй,
    устойчивый ключ к незавершённой работе. Без фильтра по составу материалов
    запрос отвечает на вопрос «что сейчас происходит с этим делом», с фильтром —
    на вопрос «за этот же состав материалов уже заплачено и подготовлено».
    """
    row = await _require_pool().fetchrow(
        """
        SELECT id, payment_order_id, user_key, case_id,
               status, stage, progress, error_detail
        FROM korgan_miniapp_generation_jobs
        WHERE user_key=$1 AND case_id=$2
          AND ($3::text IS NULL OR case_fingerprint=$3)
        ORDER BY created_at DESC
        LIMIT 1
        """,
        user_key,
        case_id,
        case_fingerprint,
    )
    return None if row is None else _from_row(row)


async def reset_failed_job(job_id: str) -> GenerationJob:
    row = await _require_pool().fetchrow(
        """
        UPDATE korgan_miniapp_generation_jobs
        SET status='queued', stage='queued', progress=0, error_detail='',
            started_at=NULL, finished_at=NULL, updated_at=NOW()
        WHERE id=$1 AND status='failed'
        RETURNING id, payment_order_id, user_key, case_id,
                  status, stage, progress, error_detail
        """,
        job_id,
    )
    if row is None:
        raise HTTPException(status_code=409, detail="Эту задачу нельзя запустить повторно")
    return _from_row(row)


async def update_job(
    job_id: str,
    *,
    status: str,
    stage: str,
    progress: int,
    error_detail: str = "",
) -> None:
    started = status == "running"
    finished = status in {"succeeded", "failed"}
    await _require_pool().execute(
        """
        UPDATE korgan_miniapp_generation_jobs
        SET status=$2, stage=$3, progress=$4, error_detail=$5,
            started_at=CASE WHEN $6 AND started_at IS NULL THEN NOW() ELSE started_at END,
            finished_at=CASE WHEN $7 THEN NOW() ELSE NULL END,
            updated_at=NOW()
        WHERE id=$1
        """,
        job_id,
        status,
        stage,
        max(0, min(int(progress), 100)),
        str(error_detail or "")[:1000],
        started,
        finished,
    )


def public_job(job: GenerationJob) -> dict[str, Any]:
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


async def _generate_payload(
    document_type: str,
    context: str,
    language: str,
    *,
    case_id: str,
    on_stage: Callable[[str, int], Awaitable[None]],
) -> dict[str, Any]:
    from korgan import miniapp_api_v2 as core
    from korgan.miniapp_professional_release import apply_release_policy

    await on_stage("legal_research", 20)
    draft, file_bytes, filename, meta = await core._generate(document_type, context, language)
    # The legal runtime currently performs research, drafting, QA and rendering in
    # one bounded call. The persisted stages become authoritative at its completed
    # boundaries; no client-side timer fabricates intermediate percentages.
    await on_stage("quality_control", 80)
    # Фоновая задача вызывает движок ниже HTTP-обёртки, поэтому политику выпуска
    # она обязана применить сама: иначе документ, забракованный финальной
    # проверкой, дошёл бы до клиента только потому, что готовился в фоне.
    payload = apply_release_policy(
        {
            "status": "document_ready",
            "title": getattr(draft, "title", "") or filename,
            "verification_status": core._status_value(getattr(draft, "status", None)),
            "verification_notes": list(meta["verification_notes"]),
            "quality_score": meta["quality_score"],
            "quality_issues": list(meta["quality_issues"]),
            "filing_ready": bool(meta["filing_ready"]),
            "release_status": str(meta["release_status"]),
            "document_base64": base64.b64encode(file_bytes).decode("ascii"),
            "filename": filename,
        },
        case_id=case_id,
    )
    await on_stage("document_render", 90)
    return payload


async def _claim_payment(job: GenerationJob) -> None:
    """Списать подтверждённую оплату ровно один раз за задачу.

    Повторный запуск той же задачи после сбоя публикации не должен требовать
    второй оплаты: ордер привязан к задаче уникально, поэтому уже списанный
    ордер этой же задачи — законное основание продолжить.
    """
    if await document_store.consume_document_order(
        job.payment_order_id,
        user_key=job.user_key,
    ):
        return
    order = await document_store.get_document_order(
        job.payment_order_id,
        user_key=job.user_key,
    )
    if order is not None and str(getattr(order, "status", "")) == "consumed":
        return
    raise RuntimeError(
        "Подтверждённая оплата документа больше не доступна. "
        "Повторно не платите — обратитесь в поддержку KORGAN."
    )


async def run_job(
    job: GenerationJob,
    *,
    identity: str,
    store: Any,
    document_type: str,
    context: str,
    language: str,
) -> None:
    async def on_stage(stage: str, progress: int) -> None:
        await update_job(
            job.id,
            status="running",
            stage=stage,
            progress=progress,
        )

    try:
        await on_stage("starting", 5)
        result = await _generate_payload(
            document_type,
            context,
            language,
            case_id=job.case_id,
            on_stage=on_stage,
        )
        # Оплата списывается до публикации: одно сохранение состояния делает
        # документ видимым обычному запросу дела, и в этот момент задача уже
        # обязана быть оплаченной, иначе клиент увидел бы готовность, за
        # которую никто не заплатил.
        await _claim_payment(job)
        # Снимок состояния из HTTP-запроса за минуту подготовки успевает
        # устареть: пользователь мог добавить материалы, создать другое дело
        # или удалить это. Сохранять снимок значило бы затирать всё это.
        state = await store.load(identity)
        case = (state.get("cases") or {}).get(job.case_id)
        if case is None:
            raise RuntimeError("Дело удалено во время подготовки документа")
        case.update(result)
        await store.save(identity, state)
        await update_job(
            job.id,
            status="succeeded",
            stage="completed",
            progress=100,
        )
    except Exception as exc:
        await update_job(
            job.id,
            status="failed",
            stage="failed",
            progress=0,
            error_detail=str(exc) or exc.__class__.__name__,
        )
        LOGGER.exception("Mini App generation job failed job_id=%s", job.id)
        raise
