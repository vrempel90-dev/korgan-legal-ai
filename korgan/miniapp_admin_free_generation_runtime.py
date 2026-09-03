from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import Header, HTTPException

from korgan import miniapp_api_v5 as v5
from korgan import miniapp_generation_jobs as jobs

LOGGER = logging.getLogger(__name__)

app = v5.app
core = v5.core
settings = v5.settings
_TASKS: dict[str, asyncio.Task[None]] = {}
_INSTALLED = False

_DISABLED_FOR_CLIENTS = (
    "Оплата документов временно отключена. Подготовка документов для обычных "
    "пользователей временно недоступна."
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


def _is_admin(identity: str) -> bool:
    try:
        return int(identity) in settings.admin_ids
    except (TypeError, ValueError):
        return False


def _consume_task_result(task: asyncio.Task[None]) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception:
        pass


async def _run_admin_generation(
    *,
    identity: str,
    case_id: str,
    document_type: str,
    context: str,
    language: str,
) -> None:
    try:
        draft, file_bytes, filename, meta = await core._generate(document_type, context, language)
        from korgan.miniapp_professional_release import apply_release_policy
        import base64

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

        state = await core.store.load(identity)
        case = (state.get("cases") or {}).get(case_id)
        if case is None:
            raise RuntimeError("case disappeared during admin generation")
        case.update(payload)
        await core.store.save(identity, state)
        LOGGER.info("ADMIN_FREE_DOCUMENT_COMPLETED case_id=%s document_type=%s", case_id, document_type)
    except Exception:
        LOGGER.exception("ADMIN_FREE_DOCUMENT_FAILED case_id=%s document_type=%s", case_id, document_type)
        raise


def install_admin_free_generation_runtime() -> None:
    """Temporary production test path for administrators while payments are off.

    PAYMENT_ENABLED remains the commercial kill switch. With payments disabled,
    normal users cannot create orders or generate documents. A Telegram id in
    ADMIN_TELEGRAM_IDS may generate directly so legal-document quality can be
    tested without touching Tole or creating fake payment state.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    _drop("/miniapp/documents/generate", "POST")

    @app.post("/miniapp/documents/generate")
    async def admin_free_generate(
        payload: core.GenerateRequest,
        x_telegram_init_data: str = Header(default=""),
    ) -> dict[str, Any]:
        identity = core.legacy._identity(x_telegram_init_data)
        state = await core.legacy._require_consent(identity)

        # When commercial payments are enabled, this temporary route must never
        # bypass them. Fail closed instead of silently becoming a free path.
        if settings.payments_enabled:
            raise HTTPException(
                status_code=503,
                detail="Временный режим тестирования отключён, потому что платёжный контур включён.",
            )

        if not _is_admin(identity):
            raise HTTPException(status_code=503, detail=_DISABLED_FOR_CLIENTS)

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

        existing = _TASKS.get(payload.case_id)
        if existing is not None and not existing.done():
            return {
                "payment_required": False,
                "generation_started": True,
                "job": {
                    "job_id": f"admin-{payload.case_id}",
                    "case_id": payload.case_id,
                    "status": "running",
                    "stage": "legal_research",
                    "progress": 20,
                    "document_ready": False,
                    "retryable": False,
                    "error": "",
                },
            }

        task = asyncio.create_task(
            _run_admin_generation(
                identity=identity,
                case_id=payload.case_id,
                document_type=document_type,
                context=context,
                language=language,
            ),
            name=f"korgan-admin-free-{payload.case_id}",
        )
        _TASKS[payload.case_id] = task

        def finished(done: asyncio.Task[None]) -> None:
            _consume_task_result(done)
            if _TASKS.get(payload.case_id) is done:
                _TASKS.pop(payload.case_id, None)

        task.add_done_callback(finished)
        return {
            "payment_required": False,
            "generation_started": True,
            "job": {
                "job_id": f"admin-{payload.case_id}",
                "case_id": payload.case_id,
                "status": "running",
                "stage": "legal_research",
                "progress": 20,
                "document_ready": False,
                "retryable": False,
                "error": "",
            },
        }

    _INSTALLED = True
    LOGGER.info("Installed admin free-generation test runtime payments_enabled=%s", settings.payments_enabled)


install_admin_free_generation_runtime()
