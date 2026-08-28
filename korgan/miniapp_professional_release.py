from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from fastapi import HTTPException

LOGGER = logging.getLogger(__name__)
_INSTALLED = False


def _issue_list(result: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("quality_issues", "verification_notes"):
        for item in list(result.get(key) or []):
            text = " ".join(str(item or "").split()).strip()
            if text and text not in values:
                values.append(text)
    return values


async def _purge_unreleased_document(core: Any, payload: Any, init_data: str, result: dict[str, Any]) -> None:
    """Make a failed quality attempt impossible to download through the case endpoint."""
    identity = core.legacy._identity(init_data)
    state = await core.legacy._require_consent(identity)
    case = state.get("cases", {}).get(payload.case_id)
    if case is None:
        return

    for key in ("document_base64", "filename"):
        case.pop(key, None)
    case["status"] = "quality_blocked"
    case["filing_ready"] = False
    case["release_status"] = "blocked"
    case["quality_score"] = result.get("quality_score")
    case["quality_issues"] = list(result.get("quality_issues") or [])
    case["verification_notes"] = list(result.get("verification_notes") or [])
    await core.store.save(identity, state)


def install_miniapp_professional_release_gate() -> None:
    """Never expose a paid Word document that the legal QA marked preliminary.

    The existing production service already performs source-bound legal research,
    drafting, deterministic checks and one bounded repair. Historically the Mini
    App still stored and returned the DOCX when those checks ended with
    filing_ready=False. This gate changes only release policy: a weak draft is
    purged and the paid order remains retryable instead of being delivered.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    from korgan import miniapp_api_v2 as core

    original: Callable[..., Awaitable[dict[str, Any]]] = core.generate_document

    async def guarded_generate_document(payload: Any, x_telegram_init_data: str = "") -> dict[str, Any]:
        result = await original(payload, x_telegram_init_data)
        if bool(result.get("filing_ready")) and str(result.get("release_status") or "") == "verified":
            return result

        issues = _issue_list(result)
        await _purge_unreleased_document(core, payload, x_telegram_init_data, result)
        detail = (
            "KORGAN не выпустил Word: документ не прошёл финальную профессиональную проверку. "
            "Оплата не должна списываться повторно; после исправления генерацию можно повторить."
        )
        if issues:
            detail += " Причина: " + "; ".join(issues[:4])
        LOGGER.error(
            "MINIAPP_PROFESSIONAL_RELEASE_BLOCK case_id=%s score=%r issues=%s",
            getattr(payload, "case_id", ""),
            result.get("quality_score"),
            issues[:6],
        )
        raise HTTPException(status_code=422, detail=detail)

    core.generate_document = guarded_generate_document  # type: ignore[assignment]
    _INSTALLED = True
    LOGGER.info("Installed Mini App professional release gate: preliminary Word delivery disabled")
