from __future__ import annotations

"""Persist calculation uncertainty as client-facing Mini App metadata.

Generation jobs store the finished document in the encrypted case state. This
runtime adds two additive fields to that same atomic publication:

* ``calculation_todo`` — short human-readable unresolved monetary points;
* ``calculation_advisory`` — the post-generation recommendation to use a KORGAN
  lawyer for those points.

The fields do not alter legal readiness. In particular, an optional penalty that
was safely excluded from a filing-ready principal claim stays optional instead
of downgrading the whole document.
"""

import base64
import logging
import sys
from typing import Any, Awaitable, Callable

from fastapi import HTTPException

from korgan import miniapp_api_v5 as v5
from korgan import miniapp_generation_api as generation_runtime
from korgan import miniapp_generation_jobs as jobs
from korgan.client_calculation_advisory import (
    build_calculation_advisory,
    unresolved_calculation_items,
)

LOGGER = logging.getLogger(__name__)
core = v5.core
_INSTALLED = False


def _fields(draft: Any, language: str) -> dict[str, Any]:
    if not hasattr(draft, "late_interest") and not hasattr(draft, "state_duty"):
        return {"calculation_todo": [], "calculation_advisory": ""}
    return {
        "calculation_todo": unresolved_calculation_items(draft, language=language),
        "calculation_advisory": build_calculation_advisory(draft, language=language),
    }


async def _generate_payload(
    document_type: str,
    context: str,
    language: str,
    *,
    case_id: str,
    on_stage: Callable[[str, int], Awaitable[None]],
) -> dict[str, Any]:
    from korgan.miniapp_professional_release import apply_release_policy

    await on_stage("legal_research", 20)
    draft, file_bytes, filename, meta = await core._generate(document_type, context, language)
    await on_stage("quality_control", 80)
    payload = {
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
        **_fields(draft, language),
    }
    payload = apply_release_policy(payload, case_id=case_id)
    await on_stage("document_render", 90)
    return payload


def _install_ready_payload() -> None:
    original = generation_runtime._document_payload
    if getattr(original, "_korgan_calculation_advisory", False):
        return

    def with_advisory(case_id: str, case: dict[str, Any]) -> dict[str, Any]:
        payload = original(case_id, case)
        payload["calculation_todo"] = list(case.get("calculation_todo") or [])
        payload["calculation_advisory"] = str(case.get("calculation_advisory") or "")
        return payload

    with_advisory._korgan_calculation_advisory = True  # type: ignore[attr-defined]
    generation_runtime._document_payload = with_advisory


def _install_admin_free_payload() -> None:
    """Patch the explicit no-payment test worker only when it is already loaded."""
    module = sys.modules.get("korgan.miniapp_admin_free_generation_runtime")
    if module is None:
        return
    original = getattr(module, "_run_free_generation", None)
    if original is None or getattr(original, "_korgan_calculation_advisory", False):
        return

    async def run_free_with_advisory(job: Any, *, context: str) -> None:
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
                    **_fields(draft, job.language),
                },
                case_id=job.case_id,
            )
            job.stage = "document_render"
            job.progress = 90

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
                "FREE_DOCUMENT_COMPLETED_WITH_CALC_ADVISORY case_id=%s document_type=%s",
                job.case_id,
                job.document_type,
            )
        except Exception as exc:
            job.status = "failed"
            job.stage = "failed"
            job.progress = 0
            job.error = module._client_error(exc)
            LOGGER.exception(
                "FREE_DOCUMENT_FAILED_WITH_CALC_ADVISORY case_id=%s document_type=%s",
                job.case_id,
                job.document_type,
            )
            raise

    run_free_with_advisory._korgan_calculation_advisory = True  # type: ignore[attr-defined]
    module._run_free_generation = run_free_with_advisory


def install_miniapp_calculation_advisory_runtime() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    jobs._generate_payload = _generate_payload
    _install_ready_payload()
    _install_admin_free_payload()
    _INSTALLED = True
    LOGGER.info("Installed Mini App unresolved-calculation client advisory")


install_miniapp_calculation_advisory_runtime()
