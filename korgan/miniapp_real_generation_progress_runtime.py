from __future__ import annotations

"""Expose real generation stages to the Mini App job endpoint.

Percentages change only when the backend crosses an actual pipeline boundary.
No timer pretends that work is complete. Stage names intentionally reuse the
existing Mini App vocabulary so old clients still render meaningful text.
"""

import base64
import logging
from types import MethodType
from typing import Any

from fastapi import HTTPException

from korgan import generation_progress
from korgan import live_article_release_runtime as live
from korgan import miniapp_admin_free_generation_runtime as free
from korgan import miniapp_api_v2 as core

LOGGER = logging.getLogger(__name__)
_INSTALLED = False


def _wrap_async_method(name: str, start_progress: int, done_progress: int) -> None:
    original = getattr(core.service, name, None)
    if original is None or getattr(original, "_korgan_real_progress", False):
        return

    async def wrapped(_self: Any, *args: Any, **kwargs: Any) -> Any:
        generation_progress.report("legal_research", start_progress)
        result = await original(*args, **kwargs)
        generation_progress.report("legal_research", done_progress)
        return result

    setattr(wrapped, "_korgan_real_progress", True)
    setattr(core.service, name, MethodType(wrapped, core.service))


def _wrap_release_metadata() -> None:
    original = core._release_metadata
    if getattr(original, "_korgan_real_progress", False):
        return

    def wrapped(*args: Any, **kwargs: Any) -> dict[str, Any]:
        generation_progress.report("quality_control", 72)
        result = original(*args, **kwargs)
        generation_progress.report("quality_control", 80)
        return result

    setattr(wrapped, "_korgan_real_progress", True)
    core._release_metadata = wrapped  # type: ignore[assignment]


def _wrap_docx_builder(name: str) -> None:
    original = getattr(core, name, None)
    if original is None or getattr(original, "_korgan_real_progress", False):
        return

    def wrapped(*args: Any, **kwargs: Any) -> bytes:
        generation_progress.report("document_render", 82)
        result = original(*args, **kwargs)
        generation_progress.report("document_render", 88)
        return result

    setattr(wrapped, "_korgan_real_progress", True)
    setattr(core, name, wrapped)


def _wrap_live_verifier() -> None:
    original = live.verify_document_articles
    if getattr(original, "_korgan_real_progress", False):
        return

    async def wrapped(file_bytes: bytes) -> None:
        # This is still part of final Word preparation for the client. Keep the
        # public stage stable while the exact backend boundary is reflected by
        # the progress jump from 90 to 96.
        generation_progress.report("document_render", 90)
        await original(file_bytes)
        generation_progress.report("document_render", 96)

    setattr(wrapped, "_korgan_real_progress", True)
    live.verify_document_articles = wrapped  # type: ignore[assignment]


async def _run_free_generation(job: Any, *, context: str) -> None:
    def update(stage: str, progress: int) -> None:
        job.stage = stage
        job.progress = progress

    job.status = "running"
    update("starting", 5)
    try:
        with generation_progress.bind(update):
            draft, file_bytes, filename, meta = await core._generate(
                job.document_type,
                context,
                job.language,
            )
            update("document_render", 97)

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
            "FREE_DOCUMENT_COMPLETED_REAL_PROGRESS case_id=%s document_type=%s",
            job.case_id,
            job.document_type,
        )
    except Exception as exc:
        job.status = "failed"
        job.stage = "failed"
        job.error = free._client_error(exc)
        LOGGER.exception(
            "FREE_DOCUMENT_FAILED_REAL_PROGRESS case_id=%s document_type=%s stage=%s progress=%s",
            job.case_id,
            job.document_type,
            job.stage,
            job.progress,
        )
        raise


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    for method_name in (
        "research_case",
        "research_contract",
        "research_response_to_claim",
        "research_pretrial",
        "research_pretrial_response",
    ):
        _wrap_async_method(method_name, 12, 42)

    # Drafting remains in the client-facing "Право и проект" stage, but its
    # progress range is distinct and advances only when drafting really starts
    # and finishes.
    for method_name in (
        "draft_claim",
        "draft_contract",
        "draft_response_to_claim",
        "draft_pretrial",
        "draft_pretrial_response",
    ):
        _wrap_async_method(method_name, 45, 70)

    _wrap_release_metadata()
    for builder in (
        "build_claim_docx",
        "build_contract_docx",
        "build_response_to_claim_docx",
        "build_pretrial_docx",
        "build_pretrial_response_docx",
    ):
        _wrap_docx_builder(builder)
    _wrap_live_verifier()

    # `_schedule` resolves this module global at run time, so replacing it here
    # affects new jobs without rebuilding routes or touching payment logic.
    free._run_free_generation = _run_free_generation
    _INSTALLED = True
    LOGGER.info("Installed real Mini App generation stage reporting")


install()
