from __future__ import annotations

import asyncio
import base64
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import Header, HTTPException

from korgan import miniapp_api_v5 as v5
from korgan import miniapp_generation_api as generation_runtime

LOGGER = logging.getLogger(__name__)

app = v5.app
core = v5.core
settings = v5.settings
_TASKS: dict[str, asyncio.Task[None]] = {}
_JOBS: dict[str, "AdminTestJob"] = {}
_CASE_JOB: dict[tuple[str, str], str] = {}
_INSTALLED = False
_HUMAN_TEXT = re.compile(r"[Ѐ-ӿ]")

_DISABLED_FOR_CLIENTS = (
    "Оплата документов временно отключена. Подготовка документов для обычных "
    "пользователей временно недоступна."
)


@dataclass
class AdminTestJob:
    id: str
    identity: str
    case_id: str
    document_type: str
    language: str
    status: str = "queued"
    stage: str = "queued"
    progress: int = 0
    error: str = ""


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


def _is_admin(identity: str) -> bool:
    try:
        return int(identity) in settings.admin_ids
    except (TypeError, ValueError):
        return False


def _require_test_admin(x_telegram_init_data: str) -> tuple[str, str]:
    identity = core.legacy._identity(x_telegram_init_data)
    if settings.payments_enabled:
        raise HTTPException(
            status_code=503,
            detail="Временный тестовый режим отключён, потому что платёжный контур включён.",
        )
    if not _is_admin(identity):
        raise HTTPException(status_code=503, detail=_DISABLED_FOR_CLIENTS)
    return identity, core.store.user_key(identity)


def _public_job(job: AdminTestJob) -> dict[str, Any]:
    return {
        "job_id": job.id,
        "case_id": job.case_id,
        "status": job.status,
        "stage": job.stage,
        "progress": max(0, min(int(job.progress), 100)),
        "document_ready": job.status == "succeeded",
        "retryable": job.status == "failed",
        "error": job.error if job.status == "failed" else "",
    }


def _client_error(exc: BaseException) -> str:
    detail = getattr(exc, "detail", "")
    text = str(detail or str(exc) or "").strip()
    if text and _HUMAN_TEXT.search(text):
        return text[:1000]
    return "Не удалось подготовить документ. Повторите подготовку — оплата не требуется."


def _consume_task_result(task: asyncio.Task[None]) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception:
        # _run_admin_generation already stores a client-safe failed state.
        pass


async def _run_admin_generation(job: AdminTestJob, *, context: str) -> None:
    job.status = "running"
    job.stage = "legal_research"
    job.progress = 20
    try:
        draft, file_bytes, filename, meta = await core._generate(job.document_type, context, job.language)
        job.stage = "quality_control"
        job.progress = 80

        from korgan.miniapp_professional_release import apply_release_policy

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
            case_id=job.case_id,
        )
        job.stage = "document_render"
        job.progress = 90

        # Re-read the encrypted state immediately before publication. This keeps
        # unrelated cases/materials created during a long generation intact.
        state = await core.store.load(job.identity)
        case = (state.get("cases") or {}).get(job.case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="Дело удалено во время подготовки документа")
        case.update(payload)
        await core.store.save(job.identity, state)

        job.status = "succeeded"
        job.stage = "completed"
        job.progress = 100
        job.error = ""
        LOGGER.info(
            "ADMIN_FREE_DOCUMENT_COMPLETED case_id=%s document_type=%s",
            job.case_id,
            job.document_type,
        )
    except Exception as exc:
        job.status = "failed"
        job.stage = "failed"
        job.progress = 0
        job.error = _client_error(exc)
        LOGGER.exception(
            "ADMIN_FREE_DOCUMENT_FAILED case_id=%s document_type=%s",
            job.case_id,
            job.document_type,
        )
        raise


def _schedule(job: AdminTestJob, *, context: str) -> None:
    existing = _TASKS.get(job.id)
    if existing is not None and not existing.done():
        return
    task = asyncio.create_task(
        _run_admin_generation(job, context=context),
        name=f"korgan-admin-free-{job.id}",
    )
    _TASKS[job.id] = task

    def finished(done: asyncio.Task[None]) -> None:
        _consume_task_result(done)
        if _TASKS.get(job.id) is done:
            _TASKS.pop(job.id, None)

    task.add_done_callback(finished)


async def _case_scope(identity: str, payload: core.GenerateRequest) -> tuple[dict[str, Any], str, str, str]:
    state = await core.legacy._require_consent(identity)
    case = (state.get("cases") or {}).get(payload.case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    document_type = str(case.get("document_type") or payload.document_type or "claim")
    if document_type not in core._DOCUMENT_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported document type")
    if payload.document_type and payload.document_type != document_type:
        raise HTTPException(status_code=409, detail="Тип документа не соответствует активному делу")
    language = "kk" if str(case.get("language") or payload.language) == "kk" else "ru"
    context = core._case_context(case)
    if not context.strip():
        raise HTTPException(status_code=422, detail="Добавьте описание ситуации или загрузите материалы дела")
    return state, document_type, language, context


async def _document_if_ready(identity: str, case_id: str) -> dict[str, Any]:
    state = await core.legacy._require_consent(identity)
    return generation_runtime._ready_document(state, case_id)


def install_admin_free_generation_runtime() -> None:
    """Temporary admin-only legal-document testing while all payments are OFF.

    No document order, QR, Tole intent or synthetic payment is created. The
    commercial payment switch stays disabled. Only Telegram ids already present
    in ADMIN_TELEGRAM_IDS receive this direct test route; every other user is
    blocked. When PAYMENTS_ENABLED becomes true, this route also fails closed so
    it cannot accidentally become a production free-generation bypass.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    for path, method in (
        ("/miniapp/documents/generate", "POST"),
        ("/miniapp/documents/generation/{job_id}", "GET"),
        ("/miniapp/cases/{case_id}/generation", "GET"),
        ("/miniapp/documents/generation/{job_id}/retry", "POST"),
    ):
        _drop(path, method)

    @app.post("/miniapp/documents/generate")
    async def admin_free_generate(
        payload: core.GenerateRequest,
        x_telegram_init_data: str = Header(default=""),
    ) -> dict[str, Any]:
        identity, _ = _require_test_admin(x_telegram_init_data)
        _, document_type, language, context = await _case_scope(identity, payload)
        key = (identity, payload.case_id)
        old_id = _CASE_JOB.get(key)
        if old_id:
            old = _JOBS.get(old_id)
            if old is not None and old.status in {"queued", "running"}:
                return {
                    "payment_required": False,
                    "generation_started": True,
                    "job": _public_job(old),
                }
            if old is not None and old.status == "succeeded":
                return {
                    "payment_required": False,
                    "generation_started": False,
                    "job": _public_job(old),
                    "document": await _document_if_ready(identity, payload.case_id),
                }

        job = AdminTestJob(
            id=f"admin-{uuid.uuid4()}",
            identity=identity,
            case_id=payload.case_id,
            document_type=document_type,
            language=language,
        )
        _JOBS[job.id] = job
        _CASE_JOB[key] = job.id
        _schedule(job, context=context)
        return {
            "payment_required": False,
            "generation_started": True,
            "job": _public_job(job),
        }

    @app.get("/miniapp/documents/generation/{job_id}")
    async def admin_generation_status(
        job_id: str,
        x_telegram_init_data: str = Header(default=""),
    ) -> dict[str, Any]:
        identity, _ = _require_test_admin(x_telegram_init_data)
        job = _JOBS.get(job_id)
        if job is None or job.identity != identity:
            raise HTTPException(status_code=404, detail="Задача подготовки документа не найдена")
        result: dict[str, Any] = {"job": _public_job(job)}
        if job.status == "succeeded":
            result["document"] = await _document_if_ready(identity, job.case_id)
        return result

    @app.get("/miniapp/cases/{case_id}/generation")
    async def admin_case_generation_status(
        case_id: str,
        x_telegram_init_data: str = Header(default=""),
    ) -> dict[str, Any]:
        identity, _ = _require_test_admin(x_telegram_init_data)
        state = await core.legacy._require_consent(identity)
        case = (state.get("cases") or {}).get(case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="Case not found")
        job_id = _CASE_JOB.get((identity, case_id))
        job = _JOBS.get(job_id or "")
        if job is None:
            return {"job": None}
        result: dict[str, Any] = {"job": _public_job(job)}
        if job.status == "succeeded":
            result["document"] = generation_runtime._ready_document(state, case_id)
        return result

    @app.post("/miniapp/documents/generation/{job_id}/retry")
    async def admin_retry_generation(
        job_id: str,
        x_telegram_init_data: str = Header(default=""),
    ) -> dict[str, Any]:
        identity, _ = _require_test_admin(x_telegram_init_data)
        old = _JOBS.get(job_id)
        if old is None or old.identity != identity:
            raise HTTPException(status_code=404, detail="Задача подготовки документа не найдена")
        if old.status != "failed":
            raise HTTPException(status_code=409, detail="Эту задачу нельзя запустить повторно")

        payload = core.GenerateRequest(
            case_id=old.case_id,
            document_type=old.document_type,
            language=old.language,
        )
        _, document_type, language, context = await _case_scope(identity, payload)
        job = AdminTestJob(
            id=f"admin-{uuid.uuid4()}",
            identity=identity,
            case_id=old.case_id,
            document_type=document_type,
            language=language,
        )
        _JOBS[job.id] = job
        _CASE_JOB[(identity, old.case_id)] = job.id
        _schedule(job, context=context)
        return {
            "payment_required": False,
            "generation_started": True,
            "job": _public_job(job),
        }

    _INSTALLED = True
    LOGGER.info(
        "Installed admin-only free document testing payments_enabled=%s admins=%s",
        settings.payments_enabled,
        len(settings.admin_ids),
    )


install_admin_free_generation_runtime()
