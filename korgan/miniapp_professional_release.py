from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from korgan.miniapp_preliminary_delivery import (
    FLAG_ENV,
    humanize,
    mark_preliminary,
)

LOGGER = logging.getLogger(__name__)
_INSTALLED = False

__all__ = [
    "FLAG_ENV",
    "ReleaseBlocked",
    "apply_release_policy",
    "install_miniapp_professional_release_gate",
    "professional_release_allowed",
]


class ReleaseBlocked(Exception):
    """Legacy compatibility type; Mini App no longer blocks an already generated Word.

    Kept because older tests/importers may reference the symbol. Production release
    policy now converts every non-filing-ready result into a clearly marked review
    draft instead of deleting the DOCX or returning HTTP 422.
    """

    def __init__(self, issues: list[str]) -> None:
        self.issues = list(issues)
        reasons = humanize(self.issues)
        detail = "Документ требует проверки перед подачей."
        if reasons:
            detail += " Проверьте: " + "; ".join(reasons[:4])
        self.detail = detail
        super().__init__(detail)


def professional_release_allowed(result: dict[str, Any]) -> bool:
    """Whether a generated Word may be labelled filing-ready without warnings."""
    return bool(result.get("filing_ready")) and str(result.get("release_status") or "") == "verified"


def _issue_list(result: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("quality_issues", "verification_notes"):
        for item in list(result.get(key) or []):
            text = " ".join(str(item or "").split()).strip()
            if text and text not in values:
                values.append(text)
    return values


def apply_release_policy(result: dict[str, Any], *, case_id: str) -> dict[str, Any]:
    """Always release an already generated Word; downgrade unsafe results visibly.

    Legal QA still decides whether the file is filing-ready. A verified result is
    returned unchanged. Any other successfully generated result is returned as a
    preliminary/review draft with a human-readable checklist. This distinction is
    critical: legal uncertainty must never be hidden, but it must also never erase
    a document that was successfully generated.

    Technical generation failures remain failures because there is no Word to
    deliver. This function only controls release of an existing generation result.
    """
    if professional_release_allowed(result):
        return result

    issues = _issue_list(result)
    LOGGER.warning(
        "MINIAPP_PROFESSIONAL_RELEASE_REVIEW_DRAFT case_id=%s score=%r issues=%s",
        case_id,
        result.get("quality_score"),
        issues[:6],
    )
    return mark_preliminary(result, issues, case_id)


def install_miniapp_professional_release_gate() -> None:
    """Guarantee delivery of every successfully generated Word document.

    The legal pipeline may mark a document non-filing-ready because a citation,
    court, amount, requisite or attachment still needs review. Those findings are
    preserved and shown to the client, but the generated DOCX is never purged and
    the API never converts that successful generation into a quality 422.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    from korgan import miniapp_api_v2 as core

    original: Callable[..., Awaitable[dict[str, Any]]] = core.generate_document

    async def guarded_generate_document(payload: Any, x_telegram_init_data: str = "") -> dict[str, Any]:
        result = await original(payload, x_telegram_init_data)
        return apply_release_policy(result, case_id=str(getattr(payload, "case_id", "")))

    core.generate_document = guarded_generate_document  # type: ignore[assignment]
    _INSTALLED = True
    LOGGER.info("Installed Mini App professional release gate: generated Word is always delivered")
